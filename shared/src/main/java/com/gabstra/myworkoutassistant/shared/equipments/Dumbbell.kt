package com.gabstra.myworkoutassistant.shared.equipments

import java.util.UUID

class Dumbbell (
    id : UUID,
    override val name: String,
    val availableDumbbells: List<BaseWeight>, // List of available dumbbells
    extraWeights: List<BaseWeight> = emptyList(),
    maxExtraWeightsPerLoadingPoint: Int = 0,
) : WeightLoadedEquipment(id,EquipmentType.DUMBBELL,extraWeights, maxExtraWeightsPerLoadingPoint, 1) {

    override fun getBaseCombinations(): Set<List<BaseWeight>> {
        return availableDumbbells.map { listOf(it) }.toSet()
    }

    override fun formatWeight(weight: Double): String {
        return "${com.gabstra.myworkoutassistant.shared.formatWeight(weight)} kg"
    }
}