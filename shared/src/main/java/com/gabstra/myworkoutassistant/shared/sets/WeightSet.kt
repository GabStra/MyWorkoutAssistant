package com.gabstra.myworkoutassistant.shared.sets

import java.util.UUID

data class WeightSet(override val id: UUID, val reps: Int, val weight: Double) : Set(id)
