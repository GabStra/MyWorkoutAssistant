package com.gabstra.myworkoutassistant.shared.workout.recovery

/**
 * Identifies the type of workout state for recovery checkpoint serialization.
 * Mirrors [WorkoutState][com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState] variants.
 */
enum class RecoveryStateType {
    SET,
    REST,
    CALIBRATION_LOAD,
    CALIBRATION_RIR,
    UNKNOWN
}
