package com.gabstra.myworkoutassistant.shared.sets

import java.util.UUID

data class BodyWeightSet(override val id: UUID, val reps: Int, val additionalWeight:Double) : Set(id)
