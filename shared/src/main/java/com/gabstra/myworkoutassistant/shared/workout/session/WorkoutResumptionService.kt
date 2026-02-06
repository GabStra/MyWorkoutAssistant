package com.gabstra.myworkoutassistant.shared.workout.session

import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.WorkoutRecord
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateQueries
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.util.UUID

internal class WorkoutResumptionService {
    fun findResumptionIndex(
        allWorkoutStates: List<WorkoutState>,
        executedSetsHistorySnapshot: List<SetHistory>,
        workoutRecord: WorkoutRecord?,
        exercisesById: Map<UUID, Exercise>
    ): Int {
        if (workoutRecord != null) {
            allWorkoutStates.forEachIndexed { index, state ->
                if (state is WorkoutState.Set &&
                    WorkoutStateQueries.matchesExerciseAndOrder(
                        state = state,
                        exerciseId = workoutRecord.exerciseId,
                        order = workoutRecord.setIndex
                    )
                ) {
                    return index
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
                        return index
                    }
                }
            }
        }

        var firstSetWithHistoryIndex: Int? = null

        allWorkoutStates.forEachIndexed { index, state ->
            val identity = WorkoutStateQueries.stateHistoryIdentity(state) ?: return@forEachIndexed
            val exercise = identity.exerciseId?.let { exercisesById[it] } ?: return@forEachIndexed

            if (!exercise.doNotStoreHistory) {
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
                    return index
                }
            }
        }

        return if (executedSetsHistorySnapshot.isEmpty()) {
            0
        } else if (firstSetWithHistoryIndex != null) {
            (allWorkoutStates.size - 1).coerceAtLeast(0)
        } else {
            0
        }
    }
}



