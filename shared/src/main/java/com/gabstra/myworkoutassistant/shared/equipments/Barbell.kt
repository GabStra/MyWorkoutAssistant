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
        return availableWeightsCombo.map { it + barWeight }.sorted().toSet()
    }

    override fun getWeightsCombinationsNoExtra(): Set<Double> {
        val availableWeightsCombo = setOf(0.0) + super.getWeightsCombinationsNoExtra()
        return availableWeightsCombo.map { it + barWeight }.sorted().toSet()
    }

    override fun getBaseCombinations(): Set<List<BaseWeight>> {
        return generateRecursiveValidSubsets(availablePlates)
    }

/*    override fun formatWeight(weight: Double): String {
        val sideWeight = (weight - barWeight) / 2

        if(sideWeight == 0.0){
            return "No Plates"
        }

        return "${com.gabstra.myworkoutassistant.shared.formatWeight(sideWeight)} x 2"
    }*/

    override fun formatWeight(weight: Double): String {
        return "${com.gabstra.myworkoutassistant.shared.formatWeight(weight)}"
    }

    override fun getWeightsCombinationsWithLabels(): Set<Pair<Double, String>> {
        val totals = getWeightsCombinations()
        return totals.map { total ->
            val plateWeight = total - barWeight
            val barWeightFormatted = com.gabstra.myworkoutassistant.shared.formatWeight(barWeight)
            val plateWeightFormatted = com.gabstra.myworkoutassistant.shared.formatWeight(plateWeight)
            
            val label = if (plateWeight == 0.0) {
                "$barWeightFormatted kg"
            } else {
                "$barWeightFormatted + $plateWeightFormatted kg"
            }
            
            Pair(total, label)
        }.toSet()
    }
}
