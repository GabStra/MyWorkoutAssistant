package com.gabstra.myworkoutassistant.shared.export

import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgressionDao
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.RestHistoryDao
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.formatNumber
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import java.util.Calendar

sealed class ExerciseHistoryMarkdownResult {
    data class Success(val markdown: String) : ExerciseHistoryMarkdownResult()
    data class Failure(val message: String) : ExerciseHistoryMarkdownResult()
}

private data class ExerciseExportSession(
    val workoutHistory: com.gabstra.myworkoutassistant.shared.WorkoutHistory,
    val activeSetHistories: List<com.gabstra.myworkoutassistant.shared.SetHistory>
)

suspend fun buildExerciseHistoryMarkdown(
    exercise: Exercise,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    restHistoryDao: RestHistoryDao,
    exerciseSessionProgressionDao: ExerciseSessionProgressionDao,
    workouts: List<Workout>,
    workoutStore: WorkoutStore
): ExerciseHistoryMarkdownResult {
    val workoutsContainingExercise = workouts.filter { workout ->
        workout.workoutComponents.any { component ->
            when (component) {
                is Exercise -> component.id == exercise.id
                is Superset -> component.exercises.any { it.id == exercise.id }
                else -> false
            }
        }
    }

    if (workoutsContainingExercise.isEmpty()) {
        return ExerciseHistoryMarkdownResult.Failure("No workouts found containing this exercise")
    }

    val completedWorkoutHistories = workoutsContainingExercise
        .flatMap { workout -> workoutHistoryDao.getWorkoutsByWorkoutId(workout.id) }
        .filter { it.isDone }
        .sortedWith(compareBy({ it.date }, { it.time }))

    if (completedWorkoutHistories.isEmpty()) {
        return ExerciseHistoryMarkdownResult.Failure("No completed sessions found for this exercise")
    }

    val sessionsWithRecordedSets = completedWorkoutHistories.mapNotNull { workoutHistory ->
        val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryIdAndExerciseId(
            workoutHistory.id,
            exercise.id
        ).sortedBy { it.order }
        val activeSetHistories = setHistories.filterForInsightComparisonSets()
        if (activeSetHistories.isEmpty()) null else ExerciseExportSession(
            workoutHistory = workoutHistory,
            activeSetHistories = activeSetHistories
        )
    }

    if (sessionsWithRecordedSets.isEmpty()) {
        return ExerciseHistoryMarkdownResult.Failure(
            "No completed sessions with recorded sets found for this exercise"
        )
    }

    val userAge = Calendar.getInstance().get(Calendar.YEAR) - workoutStore.birthDateYear
    val markdown = StringBuilder()

    val firstSessionWithSets = sessionsWithRecordedSets.firstOrNull { it.activeSetHistories.isNotEmpty() }
    val firstHistory = firstSessionWithSets?.activeSetHistories?.firstOrNull()

    val historicalEquipmentId = firstHistory?.equipmentIdSnapshot ?: exercise.equipmentId
    val equipment = historicalEquipmentId?.let { equipmentId ->
        workoutStore.equipments.find { it.id == equipmentId }
    }
    val achievableWeights = equipment?.getWeightsCombinations()?.sorted()

    markdown.append("# ${exercise.name}\n")
    markdown.append("Type: ${exercise.exerciseType}")

    if (historicalEquipmentId != null) {
        if (equipment != null) {
            markdown.append(" | Equipment: ${equipment.name}")
            if (exercise.exerciseType == ExerciseType.WEIGHT && !achievableWeights.isNullOrEmpty()) {
                markdown.append(
                    " | Weights: ${achievableWeights.joinToString(",") { weight -> formatNumber(weight) }} kg"
                )
            }
        } else {
            markdown.append(" | Equipment: Unknown")
        }
    }

    if (exercise.exerciseType == ExerciseType.BODY_WEIGHT) {
        markdown.append(" | BW: ${formatNumber(workoutStore.weightKg)} kg (current profile; historical sets use stored effective load)")
    }

    if (exercise.notes.isNotEmpty()) {
        markdown.append(" | Notes: ${exercise.notes}")
    }
    markdown.append("\n\n")

    appendLlmExportContextMarkdown(markdown, workoutStore, userAge)

    val firstSession = sessionsWithRecordedSets.first().workoutHistory
    val lastSession = sessionsWithRecordedSets.last().workoutHistory
    markdown.append(
        "Sessions: ${sessionsWithRecordedSets.size} | Range: ${firstSession.date} to ${lastSession.date}\n\n"
    )

    for ((sessionIndex, session) in sessionsWithRecordedSets.withIndex()) {
        val workoutHistory = session.workoutHistory
        val workout = workoutsContainingExercise.find { it.id == workoutHistory.workoutId }
        val workoutName = workout?.name ?: "Unknown Workout"
        val activeSetHistories = session.activeSetHistories

        val progressionData = exerciseSessionProgressionDao.getByWorkoutHistoryIdAndExerciseId(
            workoutHistory.id,
            exercise.id
        )

        val sessionBwFromSnapshot = if (exercise.exerciseType == ExerciseType.BODY_WEIGHT) {
            val firstBw = session.activeSetHistories.mapNotNull { it.setData as? BodyWeightSetData }.firstOrNull()
            val pct = firstBw?.bodyWeightPercentageSnapshot
            val eff = firstBw?.relativeBodyWeightInKg
            if (pct != null && pct > 0 && eff != null) eff / (pct / 100) else null
        } else null

        markdown.append(
            "## S${sessionIndex + 1}: ${workoutHistory.date} ${workoutHistory.time} | $workoutName | Dur: ${formatDurationForExport(workoutHistory.duration)}"
        )
        if (sessionBwFromSnapshot != null) {
            markdown.append(" | Session BW: ${formatNumber(sessionBwFromSnapshot)} kg")
        }
        markdown.append("\n")
        markdown.append(
            "Session: start at ${workoutHistory.startTime} | sessionId: ${workoutHistory.id} | globalId: ${workoutHistory.globalId}\n"
        )

        workout?.let { w ->
            templatePosition1BasedForExercise(w, exercise.id)?.let { pos ->
                val total = templateExerciseIdsInWorkoutOrder(w).size
                markdown.append("- Template position: exercise $pos of $total (flattened workout order)\n")
            }
        }

        appendSessionHeartRateMarkdown(
            markdown = markdown,
            workoutHistory = workoutHistory,
            userAge = userAge,
            workoutStore = workoutStore,
            exerciseForTargetBand = exercise
        )

        progressionData?.let { progression ->
            appendExerciseProgressionMarkdown(
                markdown = markdown,
                progression = progression,
                activeSetHistories = activeSetHistories,
                achievableWeights = achievableWeights
            )
        }

        val restsForSession =
            restHistoryDao.getByWorkoutHistoryIdAndExerciseId(workoutHistory.id, exercise.id)
        appendExerciseTimelineToMarkdown(
            markdown = markdown,
            exercise = exercise,
            activeSetHistories = activeSetHistories,
            restsForExercise = restsForSession,
            workoutHistory = workoutHistory,
            workoutStore = workoutStore,
            userAge = userAge,
            achievableWeights = achievableWeights,
            equipmentNameForHeader = equipment?.name
        )
        markdown.append("\n")
    }

    return ExerciseHistoryMarkdownResult.Success(markdown.toString())
}
