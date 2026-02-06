package com.gabstra.myworkoutassistant.shared.workout.session

import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutRecord
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateContainer
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateSequenceItem
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateSequenceOps
import java.time.Duration
import java.time.LocalDateTime
import java.util.UUID

internal class WorkoutSessionOrchestrator {
    fun selectWorkout(
        workouts: List<Workout>,
        selectedWorkoutId: UUID?
    ): Workout? {
        return workouts.find { it.id == selectedWorkoutId }
    }

    fun resolveResumeHistoryId(
        pendingResumeWorkoutHistoryId: UUID?,
        workoutRecord: WorkoutRecord?
    ): UUID? {
        return pendingResumeWorkoutHistoryId ?: workoutRecord?.workoutHistoryId
    }

    fun deriveStartWorkoutTimeFromCompletedSetHistories(
        setHistories: List<SetHistory>,
        now: LocalDateTime = LocalDateTime.now()
    ): LocalDateTime {
        val totalElapsedSeconds = setHistories
            .filter { it.startTime != null && it.endTime != null }
            .sumOf { Duration.between(it.startTime!!, it.endTime!!).seconds }
        return now.minusSeconds(totalElapsedSeconds)
    }

    fun computeResumptionIndex(
        updatedSequence: List<WorkoutStateSequenceItem>,
        executedSetsHistorySnapshot: List<SetHistory>,
        resolveIndex: (List<WorkoutState>, List<SetHistory>) -> Int
    ): Int {
        val allStates = updatedSequence.flatMap { item ->
            when (item) {
                is WorkoutStateSequenceItem.Container -> {
                    when (val container = item.container) {
                        is WorkoutStateContainer.ExerciseState -> WorkoutStateSequenceOps.flattenExerciseContainer(container)
                        is WorkoutStateContainer.SupersetState -> container.childStates
                    }
                }
                is WorkoutStateSequenceItem.RestBetweenExercises -> listOf(item.rest)
            }
        }

        val filteredStates = allStates.toMutableList()
        if (filteredStates.isNotEmpty() && filteredStates.last() is WorkoutState.Rest) {
            filteredStates.removeAt(filteredStates.size - 1)
        }

        return resolveIndex(filteredStates, executedSetsHistorySnapshot)
    }
}


