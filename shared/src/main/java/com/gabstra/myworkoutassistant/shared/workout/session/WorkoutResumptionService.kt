package com.gabstra.myworkoutassistant.shared.workout.session

import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.WorkoutRecord
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateQueries
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.util.UUID

/**
 * @param workoutRecordMatchedTemplate False when a [WorkoutRecord] was present but did not match any
 * template position; [index] was derived from SetHistory fallback. True when there was no record, or the record matched.
 */
data class ResumptionIndexResult(
    val index: Int,
    val workoutRecordMatchedTemplate: Boolean
)

internal class WorkoutResumptionService {
    /**
     * True if [record] matches at least one Set position (or Rest immediately after that Set) in [allWorkoutStates].
     */
    fun recordMatchesWorkoutStates(record: WorkoutRecord, allWorkoutStates: List<WorkoutState>): Boolean {
        allWorkoutStates.forEachIndexed { index, state ->
            if (state is WorkoutState.Set &&
                WorkoutStateQueries.matchesExerciseAndOrder(
                    state = state,
                    exerciseId = record.exerciseId,
                    order = record.setIndex
                )
            ) {
                return true
            }
            if (state is WorkoutState.Rest && index > 0) {
                val previousState = allWorkoutStates[index - 1]
                if (previousState is WorkoutState.Set &&
                    WorkoutStateQueries.matchesExerciseAndOrder(
                        state = previousState,
                        exerciseId = record.exerciseId,
                        order = record.setIndex
                    )
                ) {
                    return true
                }
            }
        }
        return false
    }

    /**
     * Resolves exercise id and set order for persisting a [WorkoutRecord] at a resumption [index] (may be Rest).
     */
    fun exerciseIdAndOrderAtResumptionIndex(
        allWorkoutStates: List<WorkoutState>,
        index: Int
    ): Pair<UUID, UInt>? {
        if (index !in allWorkoutStates.indices) return null
        var i = index
        while (i >= 0) {
            when (val w = allWorkoutStates[i]) {
                is WorkoutState.Set -> return Pair(w.exerciseId, w.setIndex)
                is WorkoutState.CalibrationLoadSelection -> return Pair(w.exerciseId, w.setIndex)
                is WorkoutState.CalibrationRIRSelection -> return Pair(w.exerciseId, w.setIndex)
                is WorkoutState.AutoRegulationRIRSelection -> return Pair(w.exerciseId, w.setIndex)
                else -> i--
            }
        }
        return null
    }

    fun findResumptionIndex(
        allWorkoutStates: List<WorkoutState>,
        executedSetsHistorySnapshot: List<SetHistory>,
        workoutRecord: WorkoutRecord?,
        exercisesById: Map<UUID, Exercise>
    ): ResumptionIndexResult {
        if (workoutRecord != null) {
            allWorkoutStates.forEachIndexed { index, state ->
                if (state is WorkoutState.Set &&
                    WorkoutStateQueries.matchesExerciseAndOrder(
                        state = state,
                        exerciseId = workoutRecord.exerciseId,
                        order = workoutRecord.setIndex
                    )
                ) {
                    return ResumptionIndexResult(index, workoutRecordMatchedTemplate = true)
                }

                if (state is WorkoutState.Rest && index > 0) {
                    val previousState = allWorkoutStates[index - 1]
                    if (previousState is WorkoutState.Set &&
                        WorkoutStateQueries.matchesExerciseAndOrder(
                            state = previousState,
                            exerciseId = workoutRecord.exerciseId,
                            order = workoutRecord.setIndex
                        )
                    ) {
                        return ResumptionIndexResult(index, workoutRecordMatchedTemplate = true)
                    }
                }
            }
        }

        var firstSetWithHistoryIndex: Int? = null

        allWorkoutStates.forEachIndexed { index, state ->
            val identity = WorkoutStateQueries.stateHistoryIdentity(state) ?: return@forEachIndexed
            identity.exerciseId?.let { exercisesById[it] } ?: return@forEachIndexed

            if (firstSetWithHistoryIndex == null && state is WorkoutState.Set) {
                firstSetWithHistoryIndex = index
            }

            val matchingSetHistory = executedSetsHistorySnapshot.firstOrNull { setHistory ->
                WorkoutStateQueries.matchesSetHistory(
                    setHistory,
                    identity.setId,
                    identity.order,
                    identity.exerciseId
                )
            }

            if (matchingSetHistory == null) {
                return ResumptionIndexResult(
                    index,
                    workoutRecordMatchedTemplate = workoutRecord == null
                )
            }
        }

        val fallbackIndex = if (executedSetsHistorySnapshot.isEmpty()) {
            0
        } else if (firstSetWithHistoryIndex != null) {
            (allWorkoutStates.size - 1).coerceAtLeast(0)
        } else {
            0
        }
        return ResumptionIndexResult(
            fallbackIndex,
            workoutRecordMatchedTemplate = workoutRecord == null
        )
    }
}
