package com.gabstra.myworkoutassistant.shared.workout.session

import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateMachine
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateQueries
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateSequenceItem
import java.time.LocalDateTime
import java.util.UUID

internal class WorkoutRefreshService {
    data class RefreshRequest(
        val targetSetId: UUID?,
        val targetExerciseId: UUID?,
        val completedMatchingCount: Int
    )

    fun createRefreshRequest(
        isRefreshing: Boolean,
        currentState: WorkoutState,
        oldHistory: List<WorkoutState>
    ): RefreshRequest? {
        if (isRefreshing) return null
        if (currentState !is WorkoutState.Set && currentState !is WorkoutState.Rest) return null

        val targetSetId = WorkoutStateQueries.stateSetId(currentState)
        val targetExerciseId = WorkoutStateQueries.stateExerciseId(currentState)
        val completedMatchingCount = oldHistory.count { state ->
            WorkoutStateQueries.stateMatchesSetAndExercise(
                state = state,
                targetSetId = targetSetId,
                targetExerciseId = targetExerciseId
            )
        }

        return RefreshRequest(
            targetSetId = targetSetId,
            targetExerciseId = targetExerciseId,
            completedMatchingCount = completedMatchingCount
        )
    }

    fun findTargetIndex(
        allStates: List<WorkoutState>,
        request: RefreshRequest
    ): Int {
        var occurrenceCount = 0
        for (i in allStates.indices) {
            val state = allStates[i]
            val matches = WorkoutStateQueries.stateMatchesSetAndExercise(
                state = state,
                targetSetId = request.targetSetId,
                targetExerciseId = request.targetExerciseId
            )
            if (!matches) continue

            occurrenceCount++
            if (occurrenceCount == request.completedMatchingCount + 1) {
                return i
            }
        }
        return -1
    }

    fun repositionToNextStateAfterTarget(
        workoutSequence: List<WorkoutStateSequenceItem>,
        targetIndex: Int
    ): WorkoutStateMachine {
        var machine = WorkoutStateMachine.fromSequence(workoutSequence, { LocalDateTime.now() }, targetIndex)
        if (!machine.isCompleted) {
            machine = machine.next()
        }
        return machine
    }
}



