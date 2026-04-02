package com.gabstra.myworkoutassistant.shared.workout.display

import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import java.util.UUID

/**
 * Display model for one row in the exercise set viewer. Each row corresponds to one state
 * from the exercise's container in the workout state machine.
 */
sealed class ExerciseSetDisplayRow {
    data class SetRow(val state: WorkoutState.Set) : ExerciseSetDisplayRow()
    data class RestRow(val state: WorkoutState.Rest) : ExerciseSetDisplayRow()
    data class CalibrationLoadSelectRow(val state: WorkoutState.CalibrationLoadSelection) : ExerciseSetDisplayRow()
    data class CalibrationRIRRow(val state: WorkoutState.CalibrationRIRSelection) : ExerciseSetDisplayRow()

    fun workoutState(): WorkoutState = when (this) {
        is SetRow -> state
        is RestRow -> state
        is CalibrationLoadSelectRow -> state
        is CalibrationRIRRow -> state
    }
}

fun toExerciseSetDisplayRowOrNull(state: WorkoutState): ExerciseSetDisplayRow? {
    return when (state) {
        is WorkoutState.Set -> ExerciseSetDisplayRow.SetRow(state)
        is WorkoutState.Rest -> ExerciseSetDisplayRow.RestRow(state)
        is WorkoutState.CalibrationLoadSelection ->
            if (state.isLoadConfirmed) null else ExerciseSetDisplayRow.CalibrationLoadSelectRow(state)
        is WorkoutState.CalibrationRIRSelection -> ExerciseSetDisplayRow.CalibrationRIRRow(state)
        is WorkoutState.AutoRegulationRIRSelection -> null
        else -> null
    }
}

fun buildExerciseSetDisplayRows(
    viewModel: WorkoutViewModel,
    exerciseId: UUID,
): List<ExerciseSetDisplayRow> {
    return viewModel.getStatesForExercise(exerciseId).mapNotNull(::toExerciseSetDisplayRowOrNull)
}

fun buildSupersetSetDisplayRows(
    viewModel: WorkoutViewModel,
    supersetId: UUID,
): List<ExerciseSetDisplayRow> {
    return viewModel.getStatesForSuperset(supersetId).mapNotNull(::toExerciseSetDisplayRowOrNull)
}

fun ExerciseSetDisplayRow.setLikeIdOrNull(): UUID? = when (this) {
    is ExerciseSetDisplayRow.SetRow -> state.set.id
    is ExerciseSetDisplayRow.RestRow -> state.set.id
    is ExerciseSetDisplayRow.CalibrationLoadSelectRow -> state.calibrationSet.id
    is ExerciseSetDisplayRow.CalibrationRIRRow -> state.calibrationSet.id
}

private data class DisplayRowIdentity(
    val exerciseId: UUID?,
    val setId: UUID?,
    val order: UInt?,
)

private fun WorkoutState.displayRowIdentityOrNull(): DisplayRowIdentity? = when (this) {
    is WorkoutState.Set -> DisplayRowIdentity(
        exerciseId = exerciseId,
        setId = set.id,
        order = setIndex
    )
    is WorkoutState.Rest -> DisplayRowIdentity(
        exerciseId = exerciseId,
        setId = set.id,
        order = order
    )
    is WorkoutState.CalibrationLoadSelection -> DisplayRowIdentity(
        exerciseId = exerciseId,
        setId = calibrationSet.id,
        order = setIndex
    )
    is WorkoutState.CalibrationRIRSelection -> DisplayRowIdentity(
        exerciseId = exerciseId,
        setId = calibrationSet.id,
        order = setIndex
    )
    is WorkoutState.AutoRegulationRIRSelection -> DisplayRowIdentity(
        exerciseId = exerciseId,
        setId = workSet.id,
        order = setIndex
    )
    else -> null
}

fun findDisplayRowIndex(
    displayRows: List<ExerciseSetDisplayRow>,
    stateToMatch: WorkoutState,
    fallbackSetId: UUID?,
): Int {
    val byReference = displayRows.indexOfFirst { it.workoutState() === stateToMatch }
    if (byReference >= 0) return byReference

    val targetIdentity = stateToMatch.displayRowIdentityOrNull()
    if (targetIdentity != null) {
        val byIdentity = displayRows.indexOfFirst { row ->
            row.workoutState().displayRowIdentityOrNull() == targetIdentity
        }
        if (byIdentity >= 0) return byIdentity
    }

    if (fallbackSetId != null) {
        val bySetId = displayRows.indexOfFirst { it.setLikeIdOrNull() == fallbackSetId }
        if (bySetId >= 0) return bySetId
    }

    return 0
}
