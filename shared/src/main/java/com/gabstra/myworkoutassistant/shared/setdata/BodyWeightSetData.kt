package com.gabstra.myworkoutassistant.shared.setdata

data class BodyWeightSetData(
    val actualReps: Int,
    val additionalWeight:Double,
    val relativeBodyWeightInKg: Double,
    val volume: Double,
    val subCategory: SetSubCategory = SetSubCategory.WorkSet
): SetData(){
    fun getWeight(): Double {
        return (relativeBodyWeightInKg + additionalWeight)
    }

    fun calculateVolume(): Double {
        val weight = getWeight()
        return weight * actualReps
    }
}
