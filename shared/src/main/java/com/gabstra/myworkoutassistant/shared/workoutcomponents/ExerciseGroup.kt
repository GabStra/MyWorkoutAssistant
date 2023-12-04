package com.gabstra.myworkoutassistant.shared.workoutcomponents

data class ExerciseGroup(
    override val name: String,
    override val restTimeInSec: Int,
    val workoutComponents: List<WorkoutComponent>,
) : WorkoutComponent(name, restTimeInSec)