package com.gabstra.myworkoutassistant.shared.workoutcomponents

import java.util.UUID

sealed class WorkoutComponent(
    open val id: UUID,
    open val enabled: Boolean,
)