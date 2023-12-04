package com.gabstra.myworkoutassistant.shared.workoutcomponents

data class ExerciseGroup(
    override val name: String,
    override val restTimeInSec: Int,
    override val enabled: Boolean,
    override val skipWorkoutRest: Boolean,
    val workoutComponents: List<WorkoutComponent>,
) : WorkoutComponent(name, restTimeInSec, enabled, skipWorkoutRest)