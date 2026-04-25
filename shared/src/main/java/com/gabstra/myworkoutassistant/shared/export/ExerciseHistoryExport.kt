package com.gabstra.myworkoutassistant.shared.export

import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgressionDao
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.RestHistory
import com.gabstra.myworkoutassistant.shared.RestHistoryDao
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.formatNumber
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
import com.gabstra.myworkoutassistant.shared.workout.history.elapsedSecondsFromHistoryBounds
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import java.util.Calendar
import kotlin.math.roundToInt

sealed class ExerciseHistoryMarkdownResult {
    data class Success(val markdown: String) : ExerciseHistoryMarkdownResult()
    data class Failure(val message: String) : ExerciseHistoryMarkdownResult()
}

private data class ExerciseExportSession(
    val workoutHistory: com.gabstra.myworkoutassistant.shared.WorkoutHistory,
    val setHistories: List<com.gabstra.myworkoutassistant.shared.SetHistory>,
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
            setHistories = setHistories,
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

        markdown.append("## S${sessionIndex + 1} (${workoutHistory.startTime.toLocalDate()})\n")

        val restsForSession =
            restHistoryDao.getByWorkoutHistoryIdAndExerciseId(workoutHistory.id, exercise.id)

        appendExerciseSessionCompactSummaryMarkdown(
            markdown = markdown,
            workoutName = workoutName,
            sessionDurationSeconds = workoutHistory.duration,
            sessionBodyWeightKg = sessionBwFromSnapshot,
            activeSetHistories = activeSetHistories,
            restsForExercise = restsForSession,
            workoutHistory = workoutHistory,
            userAge = userAge,
            workoutStore = workoutStore,
            exercise = exercise,
            progression = progressionData,
            achievableWeights = achievableWeights,
        )
        markdown.append("\n")
    }

    return ExerciseHistoryMarkdownResult.Success(markdown.toString())
}

private fun appendExerciseSessionCompactSummaryMarkdown(
    markdown: StringBuilder,
    workoutName: String,
    sessionDurationSeconds: Int,
    sessionBodyWeightKg: Double?,
    activeSetHistories: List<SetHistory>,
    restsForExercise: List<RestHistory>,
    workoutHistory: com.gabstra.myworkoutassistant.shared.WorkoutHistory,
    userAge: Int,
    workoutStore: WorkoutStore,
    exercise: Exercise,
    progression: com.gabstra.myworkoutassistant.shared.ExerciseSessionProgression?,
    achievableWeights: List<Double>?,
) {
    val executedSets = activeSetHistories.toSimpleSets(achievableWeights)
    markdown.append("### Performance\n")
    val setsLine = if (executedSets.isEmpty()) {
        "none"
    } else {
        executedSets.joinToString(", ") { it.toCompactToken() }
    }
    markdown.append("- Sets: $setsLine\n")

    val topSet = executedSets.maxWithOrNull(compareBy<SimpleSet>({ it.weight }, { it.reps }))
    markdown.append("- Top set: ${topSet?.toCompactToken() ?: "none"}\n")
    markdown.append("- Total reps: ${executedSets.sumOf { it.reps }}\n")
    markdown.append("- Rest: ${formatCompactRestSummary(restsForExercise)}\n")
    markdown.append("\n")

    markdown.append("### Context\n")
    markdown.append("- Workout: $workoutName\n")
    markdown.append("- Session duration: ${formatDurationForExport(sessionDurationSeconds)}\n")
    sessionBodyWeightKg?.let { bodyWeight ->
        markdown.append("- Session BW: ${formatNumber(bodyWeight)} kg\n")
    }
    buildExerciseHeartRateContextLines(
        workoutHistory = workoutHistory,
        activeSetHistories = activeSetHistories,
        restsForExercise = restsForExercise,
        userAge = userAge,
        workoutStore = workoutStore,
        exercise = exercise
    ).forEach { line -> markdown.append("- $line\n") }
    markdown.append("\n")

    markdown.append("### Target\n")
    val plannedSets = progression?.expectedSets.orEmpty()
    val plannedLine = if (plannedSets.isEmpty()) {
        "none"
    } else {
        plannedSets.joinToString(", ") { "${formatNumber(it.weight)}x${it.reps}" }
    }
    markdown.append("- Planned sets: $plannedLine\n")
    markdown.append("- Outcome: ${describeOutcome(executedSets, plannedSets)}\n")
}

private fun List<SetHistory>.toSimpleSets(
    achievableWeights: List<Double>?,
): List<SimpleSet> = mapNotNull { setHistory ->
    when (val setData = setHistory.setData) {
        is WeightSetData -> {
            val adjustedWeight = normalizeWeightForExport(setData.actualWeight, achievableWeights)
            SimpleSet(adjustedWeight, setData.actualReps)
        }
        is BodyWeightSetData -> SimpleSet(setData.getWeight(), setData.actualReps)
        else -> null
    }
}

private fun SimpleSet.toCompactToken(): String = "${formatNumber(weight)}x$reps"

private fun formatCompactRestSummary(
    restsForExercise: List<RestHistory>,
): String {
    val seconds = restsForExercise.mapNotNull { restHistory ->
        val planned = (restHistory.setData as? RestSetData)?.startTimer?.coerceAtLeast(0) ?: 0
        val elapsed = elapsedSecondsFromHistoryBounds(restHistory.startTime, restHistory.endTime)
        (elapsed ?: planned).takeIf { it > 0 }
    }
    if (seconds.isEmpty()) return "none recorded"

    val avg = seconds.average().roundToInt()
    val joined = seconds.joinToString(", ") { "${it}s" }
    return "$joined (avg ${avg}s)"
}

private fun buildExerciseHeartRateContextLines(
    workoutHistory: com.gabstra.myworkoutassistant.shared.WorkoutHistory,
    activeSetHistories: List<SetHistory>,
    restsForExercise: List<RestHistory>,
    userAge: Int,
    workoutStore: WorkoutStore,
    exercise: Exercise,
): List<String> {
    val block = StringBuilder()
    appendExerciseHeartRateMarkdown(
        markdown = block,
        workoutHistory = workoutHistory,
        setHistories = activeSetHistories,
        restsForExercise = restsForExercise,
        userAge = userAge,
        workoutStore = workoutStore,
        exerciseForTargetBand = exercise
    )
    if (block.isBlank()) {
        return listOf(
            "Exercise HR duration: none recorded",
            "HR zones: none recorded"
        )
    }

    val duration = Regex("""^- Duration:\s*(.+)$""", RegexOption.MULTILINE)
        .find(block.toString())
        ?.groupValues
        ?.getOrNull(1)
        ?.trim()
    val zones = Regex("""^- Zone time:\s*(.+)$""", RegexOption.MULTILINE)
        .find(block.toString())
        ?.groupValues
        ?.getOrNull(1)
        ?.trim()

    return listOf(
        "Exercise HR duration: ${duration ?: "none recorded"}",
        "HR zones: ${zones ?: "none recorded"}"
    )
}

private fun describeOutcome(
    executedSets: List<SimpleSet>,
    plannedSets: List<SimpleSet>,
): String {
    if (plannedSets.isEmpty()) return "not available"
    if (executedSets.isEmpty()) return "below"

    val executedTop = executedSets.maxWithOrNull(compareBy<SimpleSet>({ it.weight }, { it.reps }))
    val plannedTop = plannedSets.maxWithOrNull(compareBy<SimpleSet>({ it.weight }, { it.reps }))
    val executedReps = executedSets.sumOf { it.reps }
    val plannedReps = plannedSets.sumOf { it.reps }

    if (executedTop != null && plannedTop != null) {
        if (executedTop.weight > plannedTop.weight) return "exceeded"
        if (executedTop.weight < plannedTop.weight) return "below"
    }

    return when {
        executedReps > plannedReps -> "exceeded"
        executedReps < plannedReps -> "below"
        else -> "matched"
    }
}
