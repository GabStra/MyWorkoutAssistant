package com.gabstra.myworkoutassistant.shared

import java.util.UUID

data class WorkoutPlan(
    val id: UUID,
    val name: String,
    val workoutIds: List<UUID>,
    val order: Int
)

