package com.gabstra.myworkoutassistant.shared.workoutcomponents

import java.util.UUID

data class Superset(
    override val id: UUID,
    override val enabled: Boolean,
    val exercises: List<Exercise>,
    val timeInSeconds: Int
) : WorkoutComponent(id,enabled)
