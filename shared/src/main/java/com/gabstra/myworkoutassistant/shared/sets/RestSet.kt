package com.gabstra.myworkoutassistant.shared.sets

import java.util.UUID

data class RestSet(override val id: UUID, val timeInSeconds: Int,val isRestPause: Boolean = false): Set(id)
