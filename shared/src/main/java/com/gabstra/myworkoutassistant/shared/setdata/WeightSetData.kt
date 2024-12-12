package com.gabstra.myworkoutassistant.shared.setdata

import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Equipment

data class WeightSetData (val actualReps: Int, val actualWeight: Double, val volume: Double) : SetData(){
    fun getWeight(equipment: Equipment?): Double {
        if(equipment != null){
            if(equipment is Barbell){
                return equipment.barWeight + (actualWeight*equipment.volumeMultiplier)
            }

            return actualWeight * equipment.volumeMultiplier
        }

        return actualWeight
    }

    fun calculateVolume(equipment: Equipment?): Double {
        val weight = getWeight(equipment)
        return weight * actualReps
    }
}