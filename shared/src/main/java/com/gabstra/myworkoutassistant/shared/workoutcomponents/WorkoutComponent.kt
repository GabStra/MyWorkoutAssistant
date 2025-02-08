package com.gabstra.myworkoutassistant.shared.workoutcomponents

import java.util.UUID

sealed class WorkoutComponent(
    @Transient
    open val id: UUID,
    @Transient
    open val enabled: Boolean,
)