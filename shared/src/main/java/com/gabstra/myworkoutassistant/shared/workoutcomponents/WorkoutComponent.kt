package com.gabstra.myworkoutassistant.shared.workoutcomponents

sealed class WorkoutComponent(
    open val name: String,
    open val restTimeInSec: Int,
    open val enabled: Boolean,
    open val skipWorkoutRest: Boolean,
)