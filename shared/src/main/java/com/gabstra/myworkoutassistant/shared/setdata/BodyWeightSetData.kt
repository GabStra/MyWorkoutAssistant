package com.gabstra.myworkoutassistant.shared.setdata

import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Equipment
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise

data class BodyWeightSetData(
    val actualReps: Int,
    val additionalWeight:Double,
    val relativeBodyWeightInKg: Double,
    val volume: Double
): SetData(){
    fun getWeight(equipment: Equipment?): Double {
        if(equipment != null){
            if(equipment is Barbell){
                return equipment.barWeight + relativeBodyWeightInKg + (additionalWeight*equipment.volumeMultiplier)
            }

            return (relativeBodyWeightInKg + (additionalWeight*equipment.volumeMultiplier))
        }

        return (relativeBodyWeightInKg + additionalWeight)
    }

    fun calculateVolume(equipment: Equipment?): Double {
        val weight = getWeight(equipment)
        return weight * actualReps
    }
}
