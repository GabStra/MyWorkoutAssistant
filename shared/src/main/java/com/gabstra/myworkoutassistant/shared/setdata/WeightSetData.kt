package com.gabstra.myworkoutassistant.shared.setdata

data class WeightSetData (val actualReps: Int, val actualWeight: Double, val volume: Double) : SetData(){
    fun getWeight(): Double {
        return actualWeight
    }

    fun calculateVolume(): Double {
        val weight = getWeight()
        return weight * actualReps
    }

    fun calculateRelativeVolume(oneRepMax:Double): Double {
        val weight = getWeight()
        val intensity = weight / oneRepMax
        return intensity * actualReps
    }
}