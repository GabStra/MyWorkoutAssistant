package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import java.util.UUID

data class Workout(
    val id: UUID,
    val name: String,
    val description: String,
    val workoutComponents: List<WorkoutComponent>,
    val restTimeInSec: Int,
    val enabled: Boolean = true,
    val usePolarDevice: Boolean = false,
)
