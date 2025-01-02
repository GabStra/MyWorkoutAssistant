package com.gabstra.myworkoutassistant.shared.setdata

import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Equipment

data class WeightSetData (val actualReps: Int, val actualWeight: Double, val volume: Double) : SetData(){
    fun getWeight(equipment: Equipment?): Double {
        return if(equipment is Barbell){
            equipment.barWeight + (actualWeight*equipment.volumeMultiplier)
        }else if(equipment != null){
            actualWeight*equipment.volumeMultiplier
        }else {
            actualWeight
        }
    }

    fun calculateVolume(equipment: Equipment?): Double {
        val weight = getWeight(equipment)
        return weight * actualReps
    }
}