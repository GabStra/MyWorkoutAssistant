package com.gabstra.myworkoutassistant.preview

import com.gabstra.myworkoutassistant.shared.workout.state.ExerciseChildItem
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateContainer
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateMachine
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateSequenceItem
import java.time.LocalDateTime
import java.util.UUID

internal fun createPreviewWorkoutStateMachine(
    states: List<WorkoutState>,
    timeProvider: () -> LocalDateTime = { LocalDateTime.now() },
    startIndex: Int = 0,
): WorkoutStateMachine {
    val previewExerciseId = states
        .filterIsInstance<WorkoutState.Set>()
        .firstOrNull()
        ?.exerciseId
        ?: UUID.randomUUID()
    val sequence = listOf(
        WorkoutStateSequenceItem.Container(
            WorkoutStateContainer.ExerciseState(
                exerciseId = previewExerciseId,
                childItems = states
                    .map(ExerciseChildItem::Normal)
                    .toMutableList(),
            ),
        ),
    )
    return WorkoutStateMachine.fromSequence(
        sequence = sequence,
        timeProvider = timeProvider,
        startIndex = startIndex,
    )
}
