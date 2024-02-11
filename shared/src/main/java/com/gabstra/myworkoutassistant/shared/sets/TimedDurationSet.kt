package com.gabstra.myworkoutassistant.shared.sets

import java.util.UUID

data class TimedDurationSet(override val id: UUID, val timeInMillis: Int, val autoStart:Boolean, val autoStop:Boolean) : Set(id)

