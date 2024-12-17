package com.gabstra.myworkoutassistant.shared.sets

import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Equipment
import java.util.UUID

data class WeightSet(override val id: UUID, val reps: Int, val weight: Double) : Set(id){
    fun getWeight(equipment: Equipment?): Double {
        return  if(equipment is Barbell){
            equipment.barWeight + (weight*equipment.volumeMultiplier)
        }else if(equipment != null){
            weight*equipment.volumeMultiplier
        }else {
            weight
        }
    }
}
