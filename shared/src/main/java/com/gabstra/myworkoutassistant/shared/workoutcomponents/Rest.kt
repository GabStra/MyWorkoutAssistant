package com.gabstra.myworkoutassistant.shared.workoutcomponents

import java.util.UUID

data class Rest(override val id: UUID, override val enabled: Boolean, val timeInSeconds: Int): WorkoutComponent(id,enabled)
