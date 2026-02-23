package com.gabstra.myworkoutassistant.shared.workout.state

import java.util.UUID

internal fun WorkoutState.exerciseIdOrNull(): UUID? = when (this) {
    is WorkoutState.Set -> exerciseId
    is WorkoutState.Rest -> exerciseId
    is WorkoutState.CalibrationLoadSelection -> exerciseId
    is WorkoutState.CalibrationRIRSelection -> exerciseId
    is WorkoutState.AutoRegulationRIRSelection -> exerciseId
    else -> null
}

internal fun WorkoutState.setIdOrNull(): UUID? = when (this) {
    is WorkoutState.Set -> set.id
    is WorkoutState.Rest -> set.id
    is WorkoutState.CalibrationLoadSelection -> calibrationSet.id
    is WorkoutState.CalibrationRIRSelection -> calibrationSet.id
    is WorkoutState.AutoRegulationRIRSelection -> workSet.id
    else -> null
}

internal fun WorkoutState.isCalibrationState(): Boolean = when (this) {
    is WorkoutState.CalibrationLoadSelection -> true
    is WorkoutState.CalibrationRIRSelection -> true
    is WorkoutState.Set -> isCalibrationSet
    else -> false
}

internal fun WorkoutState.isRestLike(): Boolean = this is WorkoutState.Rest

internal fun WorkoutState.isUnilateralSet(): Boolean = this is WorkoutState.Set && isUnilateral

