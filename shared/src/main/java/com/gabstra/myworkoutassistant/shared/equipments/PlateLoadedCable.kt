package com.gabstra.myworkoutassistant.shared.equipments

import java.util.UUID

class PlateLoadedCable(
    id : UUID,
    override val name: String,
    val availablePlates: List<Plate>,
    val barLength: Int,
) : WeightLoadedEquipment(id, EquipmentType.PLATELOADEDCABLE, loadingPoints = 1) {

    override fun isCombinationValid(combination: List<BaseWeight>): Boolean {
        val plates = combination.filterIsInstance<Plate>()
        return plates.sumOf { it.thickness } <= barLength
    }

    override fun getBaseCombinations(): Set< List<BaseWeight>> {
        return generateRecursiveValidSubsets(availablePlates)
    }

    override fun formatWeight(weight: Double): String {
        return "${com.gabstra.myworkoutassistant.shared.formatWeight(weight)}"
    }
}
