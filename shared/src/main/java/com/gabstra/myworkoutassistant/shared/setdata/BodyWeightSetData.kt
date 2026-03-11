package com.gabstra.myworkoutassistant.shared.setdata

data class BodyWeightSetData(
    val actualReps: Int,
    val additionalWeight: Double,
    val relativeBodyWeightInKg: Double,
    val volume: Double,
    val subCategory: SetSubCategory = SetSubCategory.WorkSet,
    val calibrationRIR: Double? = null,
    val autoRegulationRIR: Double? = null,
    /** Exercise bodyweight percentage at time of set; enables reconstructing context if exercise percentage changes later. */
    val bodyWeightPercentageSnapshot: Double? = null
): SetData() {
    fun getWeight(): Double {
        return (relativeBodyWeightInKg + additionalWeight)
    }

    fun calculateVolume(): Double {
        val weight = getWeight()
        return weight * actualReps
    }

    /** Effective bodyweight used for this set (same as relativeBodyWeightInKg); for display when snapshot context is available. */
    fun getEffectiveBodyWeightInKg(): Double = relativeBodyWeightInKg
}
