package com.gabstra.myworkoutassistant.shared.equipments

import java.util.UUID

class Dumbbells (
    id : UUID,
    override val name: String,
    val availableDumbbells: List<BaseWeight>, // List of available dumbbells
    extraWeights: List<BaseWeight> = emptyList(),
    maxExtraWeightsPerLoadingPoint: Int = 0,
) : WeightLoadedEquipment(id,EquipmentType.DUMBBELLS,extraWeights, maxExtraWeightsPerLoadingPoint, 2) {

    override fun getBaseCombinations(): Set<List<BaseWeight>> {
        return availableDumbbells.map { listOf(it) }.toSet()
    }

    override fun formatWeight(weight: Double): String {
        val dumbbell = weight / 2
        return "${com.gabstra.myworkoutassistant.shared.formatWeight(dumbbell)} kg/db (tot: ${com.gabstra.myworkoutassistant.shared.formatWeight(weight)} kg)"
    }
}