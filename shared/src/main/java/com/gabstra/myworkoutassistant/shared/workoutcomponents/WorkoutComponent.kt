package com.gabstra.myworkoutassistant.shared.workoutcomponents

import java.util.UUID

sealed class WorkoutComponent(
    open val id: UUID,
    open val name: String,
    open val restTimeInSec: Int,
    open val enabled: Boolean,
    open val skipWorkoutRest: Boolean,
    open val doNotStoreHistory: Boolean,
)