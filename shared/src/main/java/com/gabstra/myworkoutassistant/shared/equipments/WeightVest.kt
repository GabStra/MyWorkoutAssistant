package com.gabstra.myworkoutassistant.shared.equipments

import java.util.UUID

class WeightVest (
    id : UUID,
    override val name: String,
    val availableWeights: List<BaseWeight>,
) : WeightLoadedEquipment(id,EquipmentType.WEIGHTVEST,emptyList(), 0, 1) {

    override fun getBaseCombinations(): Set<List<BaseWeight>>  {
        return availableWeights.map { listOf(it) }.toSet()
    }

    override fun formatWeight(weight: Double): String {
        return "${com.gabstra.myworkoutassistant.shared.formatWeight(weight)}"
    }
}