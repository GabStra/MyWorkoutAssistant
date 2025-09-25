package com.gabstra.myworkoutassistant.shared.sets

import java.util.UUID

data class WeightSet(override val id: UUID, val reps: Int, val weight: Double, val isWarmupSet: Boolean = false, val isRestPause: Boolean = false) : Set(id){
}
