package com.gabstra.myworkoutassistant.shared.export

import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgressionDao
import com.gabstra.myworkoutassistant.shared.RestHistoryDao
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.workout.history.WorkoutHistoryLayoutItem
import com.gabstra.myworkoutassistant.shared.workout.history.buildWorkoutHistoryLayout
import com.gabstra.myworkoutassistant.shared.workout.history.formatRestLineForMarkdown
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import java.util.Calendar
import java.util.UUID

sealed class WorkoutSessionMarkdownResult {
    data class Success(val markdown: String) : WorkoutSessionMarkdownResult()
    data class Failure(val message: String) : WorkoutSessionMarkdownResult()
}

private fun exercisesByIdFromWorkout(workout: Workout): Map<UUID, Exercise> {
    val map = mutableMapOf<UUID, Exercise>()
    for (c in workout.workoutComponents) {
        when (c) {
            is Exercise -> map[c.id] = c
            is Superset -> c.exercises.forEach { map[it.id] = it }
            else -> {}
        }
    }
    return map
}

private fun buildSectionMapForSessionExport(
    setHistories: List<SetHistory>,
    workout: Workout,
): LinkedHashMap<UUID, List<SetHistory>> {
    val sectionMap = linkedMapOf<UUID, List<SetHistory>>()
    val consumedHistoryIds = mutableSetOf<UUID>()
    for (superset in workout.workoutComponents.filterIsInstance<Superset>()) {
        val supersetSetHistories = setHistories
            .filter { it.supersetId == superset.id }
            .sortedWith(
                compareBy<SetHistory>(
                    { it.executionSequence == null },
                    { it.executionSequence ?: UInt.MAX_VALUE },
                    { it.startTime },
                    { it.order }
                )
            )
        if (supersetSetHistories.isNotEmpty()) {
            sectionMap[superset.id] = supersetSetHistories
            consumedHistoryIds.addAll(supersetSetHistories.map { it.id })
        }
    }
    val remainingByExerciseId = setHistories
        .filter { it.exerciseId != null && it.id !in consumedHistoryIds }
        .groupBy { it.exerciseId!! }
    sectionMap.putAll(remainingByExerciseId)
    return sectionMap
}

private fun resolveEquipmentForExercise(
    exercise: Exercise,
    activeSetHistories: List<SetHistory>,
    workoutStore: WorkoutStore,
): WeightLoadedEquipment? {
    val historicalEquipmentId = activeSetHistories.firstOrNull()?.equipmentIdSnapshot ?: exercise.equipmentId
    return historicalEquipmentId?.let { eid ->
        workoutStore.equipments.find { it.id == eid }
    }
}

suspend fun buildWorkoutSessionMarkdown(
    workoutHistoryId: UUID,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    restHistoryDao: RestHistoryDao,
    exerciseSessionProgressionDao: ExerciseSessionProgressionDao,
    workoutStore: WorkoutStore,
): WorkoutSessionMarkdownResult {
    val workoutHistory = workoutHistoryDao.getWorkoutHistoryById(workoutHistoryId)
        ?: return WorkoutSessionMarkdownResult.Failure("Workout session not found")
    val workout = workoutStore.workouts.find { it.id == workoutHistory.workoutId }
        ?: return WorkoutSessionMarkdownResult.Failure("Workout definition not found")

    val userAge = Calendar.getInstance().get(Calendar.YEAR) - workoutStore.birthDateYear
    val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryIdOrdered(workoutHistoryId)
    val sessionRestHistories = restHistoryDao.getByWorkoutHistoryIdOrdered(workoutHistoryId)
    val sectionMap = buildSectionMapForSessionExport(setHistories, workout)
    val layout = buildWorkoutHistoryLayout(
        workout,
        sectionMap,
        sessionRestHistories,
        activeExerciseId = null
    )
    val exercisesById = exercisesByIdFromWorkout(workout)
    val supersetsById = workout.workoutComponents.filterIsInstance<Superset>().associateBy { it.id }
    val markdown = StringBuilder()

    markdown.append("# ${workout.name}\n")
    markdown.append(
        "${workoutHistory.date} ${workoutHistory.time} | Dur: ${formatDurationForExport(workoutHistory.duration)}\n"
    )
    if (workout.description.isNotBlank()) {
        markdown.append("${workout.description}\n")
    }
    markdown.append("\n")
    appendLlmExportContextMarkdown(markdown, workoutStore, userAge)
    appendSessionHeartRateMarkdown(
        markdown = markdown,
        workoutHistory = workoutHistory,
        userAge = userAge,
        workoutStore = workoutStore,
        exerciseForTargetBand = null
    )

    for (item in layout) {
        when (item) {
            is WorkoutHistoryLayoutItem.ExerciseSection -> {
                val exercise = exercisesById[item.exerciseId] ?: continue
                val allSets = sectionMap[item.exerciseId].orEmpty()
                val active = allSets.filterForInsightComparisonSets()
                if (active.isEmpty()) continue
                markdown.append("### ${exercise.name}\n")
                val comparableSessions = loadComparableExerciseSessions(
                    exercise = exercise,
                    workouts = workoutStore.workouts,
                    workoutHistoryDao = workoutHistoryDao,
                    setHistoryDao = setHistoryDao,
                    exerciseSessionProgressionDao = exerciseSessionProgressionDao
                )
                val progression = exerciseSessionProgressionDao.getByWorkoutHistoryIdAndExerciseId(
                    workoutHistory.id,
                    exercise.id
                )
                val equipment = resolveEquipmentForExercise(exercise, active, workoutStore)
                val achievableWeights = equipment?.getWeightsCombinations()?.sorted()
                val selectedSessionIndex = comparableSessions.indexOfFirst {
                    it.workoutHistory.id == workoutHistory.id
                }
                val selectedSession = if (selectedSessionIndex >= 0) {
                    comparableSessions[selectedSessionIndex]
                } else {
                    ComparableExerciseSession(
                        workoutHistory = workoutHistory,
                        workout = workout,
                        activeSetHistories = active,
                        progression = progression
                    )
                }
                val sessionsThroughSelected = if (selectedSessionIndex >= 0) {
                    comparableSessions.take(selectedSessionIndex + 1)
                } else {
                    listOf(selectedSession)
                }
                val previousSession = if (selectedSessionIndex > 0) {
                    comparableSessions[selectedSessionIndex - 1]
                } else {
                    null
                }
                val bestSession = if (selectedSessionIndex >= 0) {
                    findBestSessionThroughIndex(comparableSessions, selectedSessionIndex, achievableWeights)
                } else {
                    selectedSession
                }
                appendExerciseContextMarkdown(markdown, exercise, workoutStore, equipment?.name)
                appendPlannedMarkdown(markdown, exercise)
                appendExecutedSummaryMarkdown(markdown, selectedSession, achievableWeights)
                appendHistoricalSessionBlockMarkdown(
                    markdown = markdown,
                    heading = "Previous Session",
                    session = previousSession,
                    achievableWeights = achievableWeights
                )
                appendHistoricalSessionBlockMarkdown(
                    markdown = markdown,
                    heading = "Best To Date",
                    session = bestSession,
                    achievableWeights = achievableWeights,
                    includeSelectionNote = bestSession?.workoutHistory?.id == workoutHistory.id
                )
                progression?.let {
                    appendExerciseProgressionMarkdown(markdown, it, active, achievableWeights)
                }
                val rests = restHistoryDao.getByWorkoutHistoryIdAndExerciseId(workoutHistory.id, exercise.id)
                appendExerciseRecoveryContextMarkdown(
                    markdown = markdown,
                    workoutHistory = workoutHistory,
                    activeSetHistories = active,
                    restsForExercise = rests,
                    exercise = exercise,
                    userAge = userAge,
                    workoutStore = workoutStore
                )
                appendExerciseCoachingSignalsMarkdown(
                    markdown = markdown,
                    selectedSession = selectedSession,
                    previousSession = previousSession,
                    bestSession = bestSession,
                    sessionsThroughSelected = sessionsThroughSelected,
                    achievableWeights = achievableWeights
                )
                appendExerciseTimelineToMarkdown(
                    markdown = markdown,
                    exercise = exercise,
                    setHistories = allSets,
                    restsForExercise = rests,
                    workoutHistory = workoutHistory,
                    workoutStore = workoutStore,
                    userAge = userAge,
                    achievableWeights = achievableWeights,
                    equipmentNameForHeader = equipment?.name
                )
                appendExerciseTrendMarkdown(
                    markdown = markdown,
                    sessionsThroughSelected = sessionsThroughSelected,
                    selectedSessionId = workoutHistory.id,
                    achievableWeights = achievableWeights
                )
                markdown.append("\n")
            }
            is WorkoutHistoryLayoutItem.SupersetSection -> {
                val superset = supersetsById[item.supersetId] ?: continue
                val setHistoriesSuperset = sectionMap[item.supersetId].orEmpty()
                val supersetExerciseIds = superset.exercises.map { it.id }.toSet()
                val restsForSuperset = sessionRestHistories.filter { rh ->
                    rh.exerciseId != null && rh.exerciseId in supersetExerciseIds
                }
                markdown.append("### Superset: ${superset.exercises.joinToString(" ↔ ") { it.name }}\n\n")
                for (ex in superset.exercises) {
                    val setsForEx = setHistoriesSuperset.filter { it.exerciseId == ex.id }
                    val active = setsForEx.filterForInsightComparisonSets()
                    if (active.isEmpty()) continue
                    markdown.append("#### ${ex.name}\n")
                    val progression = exerciseSessionProgressionDao.getByWorkoutHistoryIdAndExerciseId(
                        workoutHistory.id,
                        ex.id
                    )
                    val equipment = resolveEquipmentForExercise(ex, active, workoutStore)
                    val achievableWeights = equipment?.getWeightsCombinations()?.sorted()
                    val comparableSessions = loadComparableExerciseSessions(
                        exercise = ex,
                        workouts = workoutStore.workouts,
                        workoutHistoryDao = workoutHistoryDao,
                        setHistoryDao = setHistoryDao,
                        exerciseSessionProgressionDao = exerciseSessionProgressionDao
                    )
                    val selectedSessionIndex = comparableSessions.indexOfFirst {
                        it.workoutHistory.id == workoutHistory.id
                    }
                    val selectedSession = if (selectedSessionIndex >= 0) {
                        comparableSessions[selectedSessionIndex]
                    } else {
                        ComparableExerciseSession(
                            workoutHistory = workoutHistory,
                            workout = workout,
                            activeSetHistories = active,
                            progression = progression
                        )
                    }
                    val sessionsThroughSelected = if (selectedSessionIndex >= 0) {
                        comparableSessions.take(selectedSessionIndex + 1)
                    } else {
                        listOf(selectedSession)
                    }
                    val previousSession = if (selectedSessionIndex > 0) {
                        comparableSessions[selectedSessionIndex - 1]
                    } else {
                        null
                    }
                    val bestSession = if (selectedSessionIndex >= 0) {
                        findBestSessionThroughIndex(comparableSessions, selectedSessionIndex, achievableWeights)
                    } else {
                        selectedSession
                    }
                    appendExerciseContextMarkdown(markdown, ex, workoutStore, equipment?.name)
                    appendPlannedMarkdown(markdown, ex)
                    appendExecutedSummaryMarkdown(markdown, selectedSession, achievableWeights)
                    appendHistoricalSessionBlockMarkdown(
                        markdown = markdown,
                        heading = "Previous Session",
                        session = previousSession,
                        achievableWeights = achievableWeights
                    )
                    appendHistoricalSessionBlockMarkdown(
                        markdown = markdown,
                        heading = "Best To Date",
                        session = bestSession,
                        achievableWeights = achievableWeights,
                        includeSelectionNote = bestSession?.workoutHistory?.id == workoutHistory.id
                    )
                    progression?.let {
                        appendExerciseProgressionMarkdown(markdown, it, active, achievableWeights)
                    }
                    val restsForExercise = restsForSuperset.filter { it.exerciseId == ex.id }
                    appendExerciseRecoveryContextMarkdown(
                        markdown = markdown,
                        workoutHistory = workoutHistory,
                        activeSetHistories = active,
                        restsForExercise = restsForExercise,
                        exercise = ex,
                        userAge = userAge,
                        workoutStore = workoutStore
                    )
                    appendExerciseCoachingSignalsMarkdown(
                        markdown = markdown,
                        selectedSession = selectedSession,
                        previousSession = previousSession,
                        bestSession = bestSession,
                        sessionsThroughSelected = sessionsThroughSelected,
                        achievableWeights = achievableWeights
                    )
                    appendExerciseTimelineToMarkdown(
                        markdown = markdown,
                        exercise = ex,
                        setHistories = setsForEx,
                        restsForExercise = restsForExercise,
                        workoutHistory = workoutHistory,
                        workoutStore = workoutStore,
                        userAge = userAge,
                        achievableWeights = achievableWeights,
                        equipmentNameForHeader = equipment?.name
                    )
                    appendExerciseTrendMarkdown(
                        markdown = markdown,
                        sessionsThroughSelected = sessionsThroughSelected,
                        selectedSessionId = workoutHistory.id,
                        achievableWeights = achievableWeights
                    )
                    markdown.append("\n")
                }
            }
            is WorkoutHistoryLayoutItem.RestSection -> {
                val rh = item.history
                val restLine = StringBuilder(formatRestLineForMarkdown(rh))
                appendIntervalHeartRateLineForExport(
                    restLine,
                    workoutHistory,
                    rh.startTime,
                    rh.endTime,
                    exercise = null,
                    userAge = userAge,
                    workoutStore = workoutStore
                )
                markdown.append(restLine.toString()).append("\n\n")
            }
        }
    }
    return WorkoutSessionMarkdownResult.Success(markdown.toString())
}
