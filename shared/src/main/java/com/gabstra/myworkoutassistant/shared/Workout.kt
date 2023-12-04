package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent

data class Workout(
    val name: String,
    val description: String,
    val workoutComponents: List<WorkoutComponent>,
    val restTimeInSec: Int,
    val enabled: Boolean = true
)
