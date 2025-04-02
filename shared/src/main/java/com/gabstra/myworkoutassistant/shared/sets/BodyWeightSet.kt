package com.gabstra.myworkoutassistant.shared.sets

import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Equipment
import java.util.UUID

data class BodyWeightSet(override val id: UUID, val reps: Int, val additionalWeight:Double, val isWarmupSet: Boolean = false) : Set(id){
    fun getWeight(equipment: Equipment?,relativeBodyWeight:Double): Double {
        return if(equipment is Barbell){
            equipment.barWeight + relativeBodyWeight + (additionalWeight*equipment.volumeMultiplier)
        }else if(equipment != null){
            (relativeBodyWeight + (additionalWeight * equipment.volumeMultiplier))
        }else {
            (relativeBodyWeight + additionalWeight)
        }
    }
}
