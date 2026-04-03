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
import com.gabstra.myworkoutassistant.shared.stores.ExecutedRestStore
import com.gabstra.myworkoutassistant.shared.stores.ExecutedSetStore
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
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

    suspend fun loadWorkoutHistory(workout: Workout): LoadedWorkoutHistory {
        val workoutHistories = workoutHistoryDao()
            .getAllWorkoutHistories()
            .filter {
                it.isDone &&
                    it.globalId == workout.globalId
            }
            .sortedLatestFirst()

        val latestByExerciseId = mutableMapOf<UUID, List<SetHistory>>()
        val latestByExerciseAndSet = mutableMapOf<Pair<UUID, UUID>, SetHistory>()
        val exercises = flattenExercises(workout)
        val latestCompletedWorkoutHistory = workoutHistories.firstOrNull()

        Log.d(
            TAG,
            "Loading workout history for workoutGlobalId=${workout.globalId}, " +
                "latestCompletedWorkoutHistory=${latestCompletedWorkoutHistory?.id}, " +
                "latestCompletedDate=${latestCompletedWorkoutHistory?.date}, " +
                "latestCompletedTime=${latestCompletedWorkoutHistory?.time}, " +
                "doneHistories=${workoutHistories.map { "${it.id}@${it.date}T${it.time}" }}"
        )

        exercises.forEach { exercise ->
            val selectedSetHistories = latestCompletedWorkoutHistory
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

            for (setHistoryFound in selectedSetHistories) {
                latestByExerciseAndSet[exercise.id to setHistoryFound.setId] = setHistoryFound
            }

            latestByExerciseId[exercise.id] = selectedSetHistories.distinctBy { it.setId }.toList()
        }

        return LoadedWorkoutHistory(
            latestSetHistoriesByExerciseId = latestByExerciseId,
            latestSetHistoryByExerciseAndSetId = latestByExerciseAndSet
        )
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
                    it.isDone &&
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
