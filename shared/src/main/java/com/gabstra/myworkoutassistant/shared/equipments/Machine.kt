package com.gabstra.myworkoutassistant.shared.equipments

import java.util.UUID

class Machine (
    id : UUID,
    override val name: String,
    val availableWeights: List<BaseWeight>,
    extraWeights: List<BaseWeight> = emptyList(),
    maxExtraWeightsPerLoadingPoint: Int = 0,
) : WeightLoadedEquipment(id,EquipmentType.MACHINE,extraWeights, maxExtraWeightsPerLoadingPoint, 1) {

    override fun getBaseCombinations(): Set<List<BaseWeight>>  {
        return availableWeights.map { listOf(it) }.toSet()
    }

    override fun formatWeight(weight: Double): String {
        return "${com.gabstra.myworkoutassistant.shared.formatWeight(weight)}"
    }
}