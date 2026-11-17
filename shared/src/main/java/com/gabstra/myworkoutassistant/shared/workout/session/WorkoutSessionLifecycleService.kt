package com.gabstra.myworkoutassistant.shared.workout.session

import android.util.Log
import com.gabstra.myworkoutassistant.shared.RestHistoryDao
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.sortedLatestFirst
import com.gabstra.myworkoutassistant.shared.sanitizeRestPlacementInSetHistories
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.stores.ExecutedRestStore
import com.gabstra.myworkoutassistant.shared.stores.ExecutedSetStore
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
import com.gabstra.myworkoutassistant.shared.workout.model.isNormallyCompleted
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import java.util.UUID

internal class WorkoutSessionLifecycleService(
    private val executedSetStore: ExecutedSetStore,
    private val executedRestStore: ExecutedRestStore,
    private val setHistoryDao: () -> SetHistoryDao,
    private val restHistoryDao: () -> RestHistoryDao,
    private val workoutHistoryDao: () -> WorkoutHistoryDao
) {
    private companion object {
        private const val TAG = "WorkoutSessionLifecycleService"
    }

    data class LoadedWorkoutHistory(
        val latestSetHistoriesByExerciseId: Map<UUID, List<SetHistory>>,
        val latestSetHistoryByExerciseAndSetId: Map<Pair<UUID, UUID>, SetHistory>
    )

    suspend fun restoreExecutedSetsForWorkoutHistory(
        workout: Workout,
        workoutHistoryId: UUID?
    ) {
        if (workoutHistoryId == null) return

        val exercises = flattenExercises(workout)
        val allSetHistories = mutableListOf<SetHistory>()
        exercises.forEach { exercise ->
            val setHistories = sanitizeRestPlacementInSetHistories(
                setHistoryDao().getSetHistoriesByWorkoutHistoryIdAndExerciseId(
                    workoutHistoryId,
                    exercise.id
                ).sortedBy { it.order }
            )
            allSetHistories.addAll(setHistories)
        }

        executedSetStore.replaceAll(allSetHistories)
        val rests = restHistoryDao().getByWorkoutHistoryIdOrdered(workoutHistoryId)
        executedRestStore.replaceAll(rests)
    }

    suspend fun loadWorkoutHistory(
        workout: Workout,
        familyWorkouts: List<Workout> = listOf(workout),
        allWorkoutVersions: List<Workout> = familyWorkouts,
    ): LoadedWorkoutHistory {
        val allHistories = workoutHistoryDao()
            .getAllWorkoutHistories()
        val workoutHistories = allHistories.filter { it.isNormallyCompleted() && it.globalId == workout.globalId }
            .sortedLatestFirst()

        val latestByExerciseId = mutableMapOf<UUID, List<SetHistory>>()
        val latestByExerciseAndSet = mutableMapOf<Pair<UUID, UUID>, SetHistory>()
        val exercises = flattenExercises(workout)
        val recurringRowsByHistoryId = mutableMapOf<UUID, List<SetHistory>>()
        val latestCompletedWorkoutHistory = workoutHistories.firstOrNull()
        val workoutVersionsById = allWorkoutVersions.associateBy { it.id }

        Log.d(
            TAG,
            "Loading workout history for workoutGlobalId=${workout.globalId}, " +
                "latestCompletedWorkoutHistory=${latestCompletedWorkoutHistory?.id}, " +
                "latestCompletedDate=${latestCompletedWorkoutHistory?.date}, " +
                "latestCompletedTime=${latestCompletedWorkoutHistory?.time}, " +
                "doneHistories=${workoutHistories.map { "${it.id}@${it.date}T${it.time}" }}"
        )

        exercises.forEach { exercise ->
            val recurringHistories = if (
                workout.recurringSessionId != null && exercise.recurringExerciseId != null
            ) {
                loadRecurringSetHistories(
                    workout.recurringSessionId, exercise, allHistories, recurringRowsByHistoryId,
                    familyWorkouts, workoutVersionsById
                )
            } else null
            val selectedSetHistories = recurringHistories ?: latestCompletedWorkoutHistory
                ?.let { workoutHistory ->
                    val setHistories = setHistoryDao().getSetHistoriesByWorkoutHistoryIdAndExerciseIdOrdered(
                        workoutHistory.id,
                        exercise.id
                    )
                    sanitizeRestPlacementInSetHistories(setHistories)
                        .filterNot { it.isExcludedFromProgressionComparison() }
                        .distinctBy { it.setId }
                }
                ?: emptyList()

            Log.d(
                TAG,
                "Selected historical sets for exercise=${exercise.id}, workoutHistory=${latestCompletedWorkoutHistory?.id}, " +
                    "historyDate=${latestCompletedWorkoutHistory?.date}, historyTime=${latestCompletedWorkoutHistory?.time}, " +
                    "setIds=${selectedSetHistories.map { it.setId }}, orders=${selectedSetHistories.map { it.order }}"
            )

            val currentWorkingSets = exercise.sets.filter { set ->
                when (set) {
                    is RestSet -> false
                    is WeightSet -> set.subCategory == SetSubCategory.WorkSet || set.subCategory == SetSubCategory.BackOffSet
                    is BodyWeightSet -> set.subCategory == SetSubCategory.WorkSet || set.subCategory == SetSubCategory.BackOffSet
                    else -> false
                }
            }
            if (recurringHistories != null) {
                currentWorkingSets.forEachIndexed { index, set ->
                    val compatibleRows = selectedSetHistories.filter { prior ->
                        (set is WeightSet && prior.setData is WeightSetData) ||
                            (set is BodyWeightSet && prior.setData is BodyWeightSetData)
                    }
                    compatibleRows.getOrNull(index.coerceAtMost(compatibleRows.lastIndex))?.let { prior ->
                        latestByExerciseAndSet[exercise.id to set.id] = prior
                    }
                }
            } else for (setHistoryFound in selectedSetHistories) {
                latestByExerciseAndSet[exercise.id to setHistoryFound.setId] = setHistoryFound
            }

            latestByExerciseId[exercise.id] = selectedSetHistories.distinctBy { it.setId }.toList()
        }

        return LoadedWorkoutHistory(
            latestSetHistoriesByExerciseId = latestByExerciseId,
            latestSetHistoryByExerciseAndSetId = latestByExerciseAndSet
        )
    }

    private suspend fun loadRecurringSetHistories(
        recurringSessionId: UUID,
        exercise: Exercise,
        histories: List<WorkoutHistory>,
        rowsByHistoryId: MutableMap<UUID, List<SetHistory>>,
        familyWorkouts: List<Workout>,
        workoutVersionsById: Map<UUID, Workout>,
    ): List<SetHistory> {
        val trackId = exercise.recurringExerciseId ?: return emptyList()
        val sortedHistories = histories.filter { it.isNormallyCompleted() }.sortedLatestFirst()
        val legacySourceKeys = familyWorkouts.asSequence()
            .filter { it.isActive && it.recurringSessionId == recurringSessionId }
            .flatMap { familyWorkout ->
                flattenExercises(familyWorkout).asSequence()
                    .filter { it.recurringExerciseId == trackId }
                    .map { familyWorkout.globalId to it.id }
            }
            .toSet()
        suspend fun compatibleWorkingRows(history: WorkoutHistory, legacy: Boolean): List<SetHistory> {
            val rows = rowsByHistoryId[history.id]
                ?: setHistoryDao().getSetHistoriesByWorkoutHistoryIdOrdered(history.id).also {
                    rowsByHistoryId[history.id] = it
                }
            return rows
                .filter { row ->
                    if (legacy) {
                        row.recurringExerciseId == null &&
                            (history.globalId to row.exerciseId) in legacySourceKeys
                    } else {
                        history.recurringSessionId == recurringSessionId &&
                            row.recurringExerciseId == trackId
                    }
                }
                .filter { row ->
                    if (legacy) {
                        (row.equipmentIdSnapshot == null || row.equipmentIdSnapshot == exercise.equipmentId) &&
                            (row.exerciseDefinitionIdSnapshot == null || row.exerciseDefinitionIdSnapshot == exercise.exerciseDefinitionId) &&
                            (row.exerciseTypeSnapshot == null || row.exerciseTypeSnapshot == exercise.exerciseType.name)
                    } else {
                        row.equipmentIdSnapshot == exercise.equipmentId &&
                            row.exerciseDefinitionIdSnapshot == exercise.exerciseDefinitionId &&
                            row.exerciseTypeSnapshot == exercise.exerciseType.name
                    }
                }
                .filter { row ->
                    if (!legacy) return@filter true
                    val sourceWorkout = workoutVersionsById[history.workoutId] ?: return@filter true
                    val sourceExercise = flattenExercises(sourceWorkout).firstOrNull { it.id == row.exerciseId }
                        ?: return@filter false
                    sourceExercise.exerciseDefinitionId == exercise.exerciseDefinitionId &&
                        sourceExercise.exerciseType == exercise.exerciseType &&
                        sourceExercise.equipmentId == exercise.equipmentId
                }
                .filter { row ->
                    when (val data = row.setData) {
                        is WeightSetData -> (data.subCategory == SetSubCategory.WorkSet || data.subCategory == SetSubCategory.BackOffSet) &&
                            !row.skipped && data.actualWeight.isFinite() && data.actualWeight >= 0.0
                        is BodyWeightSetData -> (data.subCategory == SetSubCategory.WorkSet || data.subCategory == SetSubCategory.BackOffSet) &&
                            !row.skipped && (data.relativeBodyWeightInKg + data.additionalWeight).let { it.isFinite() && it >= 0.0 }
                        else -> false
                    }
                }
                .distinctBy { it.order }
        }

        for (history in sortedHistories.filter { it.recurringSessionId == recurringSessionId }) {
            compatibleWorkingRows(history, legacy = false).takeIf { it.isNotEmpty() }?.let { return it }
        }

        for (history in sortedHistories.filter { it.recurringSessionId == null }) {
            compatibleWorkingRows(history, legacy = true).takeIf { it.isNotEmpty() }?.let { return it }
        }
        return emptyList()
    }

    suspend fun getLastCompletedWorkoutExecutedSets(
        workoutGlobalId: UUID,
        currentWorkoutHistoryId: UUID?,
        exerciseId: UUID
    ): List<SimpleSet>? {
        val workoutHistories = workoutHistoryDao()
            .getAllWorkoutHistories()
            .filter {
                it.globalId == workoutGlobalId &&
                    it.isNormallyCompleted() &&
                    it.id != currentWorkoutHistoryId
            }
            .sortedLatestFirst()

        if (workoutHistories.isEmpty()) {
            return null
        }

        val lastCompletedWorkoutHistory = workoutHistories.first()
        val setHistories = sanitizeRestPlacementInSetHistories(
            setHistoryDao().getSetHistoriesByWorkoutHistoryIdAndExerciseId(
                lastCompletedWorkoutHistory.id,
                exerciseId
            ).sortedBy { it.order }
        )

        if (setHistories.isEmpty()) {
            return null
        }

        val executedSets = setHistories
            .filter { setHistory ->
                when (val setData = setHistory.setData) {
                    is BodyWeightSetData -> setData.subCategory != SetSubCategory.RestPauseSet && setData.subCategory != SetSubCategory.CalibrationSet
                    is WeightSetData -> setData.subCategory != SetSubCategory.RestPauseSet && setData.subCategory != SetSubCategory.CalibrationSet
                    is RestSetData -> setData.subCategory != SetSubCategory.RestPauseSet && setData.subCategory != SetSubCategory.CalibrationSet
                    else -> true
                }
            }
            .mapNotNull { setHistory ->
                when (val setData = setHistory.setData) {
                    is WeightSetData -> SimpleSet(setData.getWeight(), setData.actualReps)
                    is BodyWeightSetData -> SimpleSet(setData.getWeight(), setData.actualReps)
                    else -> null
                }
            }

        return if (executedSets.isEmpty()) null else executedSets
    }

    private fun SetHistory.isExcludedFromProgressionComparison(): Boolean {
        return when (val setData = setData) {
            is BodyWeightSetData ->
                setData.subCategory == SetSubCategory.RestPauseSet ||
                    setData.subCategory == SetSubCategory.CalibrationSet
            is WeightSetData ->
                setData.subCategory == SetSubCategory.RestPauseSet ||
                    setData.subCategory == SetSubCategory.CalibrationSet
            is RestSetData ->
                setData.subCategory == SetSubCategory.RestPauseSet ||
                    setData.subCategory == SetSubCategory.CalibrationSet
            else -> false
        }
    }

    private fun flattenExercises(workout: Workout): List<Exercise> {
        return workout.workoutComponents.filterIsInstance<Exercise>() +
            workout.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }
    }
}
