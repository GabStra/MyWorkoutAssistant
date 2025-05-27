package com.gabstra.myworkoutassistant.shared.sets

import java.util.UUID

data class BodyWeightSet(override val id: UUID, val reps: Int, val additionalWeight:Double, val isWarmupSet: Boolean = false) : Set(id){
    fun getWeight(relativeBodyWeight:Double): Double {
        return relativeBodyWeight + additionalWeight
    }
}
