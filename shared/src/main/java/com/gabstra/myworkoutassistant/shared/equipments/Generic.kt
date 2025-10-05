package com.gabstra.myworkoutassistant.shared.equipments

import java.util.UUID

class Generic (
    id : UUID,
    override val name: String,
) : WeightLoadedEquipment(id,EquipmentType.GENERIC) {

    override fun getBaseCombinations(): Set<List<BaseWeight>> {
        val availableWeights = mutableSetOf<BaseWeight>()
        var currentWeight = 0.5
        while (currentWeight <= 1000.0) {availableWeights.add(BaseWeight(currentWeight))
            currentWeight += 0.5
        }
        return availableWeights.map { listOf(it) }.toSet()
    }


    override fun formatWeight(weight: Double): String {
        return "${com.gabstra.myworkoutassistant.shared.formatWeight(weight)}"
    }

}