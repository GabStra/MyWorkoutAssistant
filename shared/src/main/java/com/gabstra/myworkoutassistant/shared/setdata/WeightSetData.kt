package com.gabstra.myworkoutassistant.shared.setdata

data class WeightSetData (val actualReps: Int, val actualWeight: Double, val volume: Double, val subCategory: SetSubCategory = SetSubCategory.WorkSet) : SetData(){
    fun getWeight(): Double {
        return actualWeight
    }

    fun calculateVolume(): Double {
        val weight = getWeight()
        return weight * actualReps
    }
}