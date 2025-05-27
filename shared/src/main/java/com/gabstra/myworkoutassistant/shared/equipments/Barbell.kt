package com.gabstra.myworkoutassistant.shared.equipments

import java.util.UUID

class Barbell(
    id : UUID,
    override val name: String,
    val availablePlates: List<Plate>, // List of available plates
    val barLength: Int,
    val barWeight: Double, // Weight of the bar in kg
) : WeightLoadedEquipment(id, EquipmentType.BARBELL, loadingPoints =  2) {

    override fun isCombinationValid(combination: List<BaseWeight>): Boolean {
        val plates = combination.filterIsInstance<Plate>()
        return plates.sumOf { it.thickness } <= barLength
    }

    override fun getWeightsCombinations(): Set<Double> {
        val availableWeightsCombo = setOf(0.0) + super.getWeightsCombinations()
        return availableWeightsCombo.map { it + barWeight }.toSet()
    }

    override fun getBaseCombinations(): Set<List<BaseWeight>> {
        return generateRecursiveValidSubsets(availablePlates)
    }

    override fun formatWeight(weight: Double): String {
        val sideWeight = (weight - barWeight) / 2
        return "${com.gabstra.myworkoutassistant.shared.formatWeight(weight)} kg (${com.gabstra.myworkoutassistant.shared.formatWeight(sideWeight)} kg/side)"
    }
}
