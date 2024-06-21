package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import java.time.LocalDate
import java.util.UUID

data class Workout(
    val id: UUID,
    val name: String,
    val description: String,
    val workoutComponents: List<WorkoutComponent>,
    val order : Int,
    val restTimeInSec: Int,
    val enabled: Boolean = true,
    val usePolarDevice: Boolean = false,
    val creationDate: LocalDate,
    val previousVersionId: UUID? = null,
    val nextVersionId: UUID? = null,
    val isActive: Boolean = true,
    val timesCompletedInAWeek: Int? = null,
)
