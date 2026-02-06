package com.gabstra.myworkoutassistant.shared.workout.ui

/**
 * High-level workout session lifecycle.
 * This is distinct from [com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState],
 * which represents the current navigable step in the workout sequence.
 */
enum class WorkoutSessionPhase {
    PREPARING,
    READY,
    ACTIVE,
    COMPLETED
}
