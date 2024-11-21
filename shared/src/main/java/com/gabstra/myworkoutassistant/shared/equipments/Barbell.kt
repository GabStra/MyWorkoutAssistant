package com.gabstra.myworkoutassistant.shared.equipments

import java.util.UUID

class Barbell(
    id : UUID,
    override val name: String,
    val availablePlates: List<Plate>, // List of available plates
    val barLength: Int, // Total length of the bar in mm
    additionalPlates: List<Plate> = emptyList(),
    maxAdditionalItems: Int = 0
) : Equipment(id,additionalPlates, maxAdditionalItems, EquipmentType.BARBELL) {

    override fun calculateBaseCombinations(): Set<Double> {
        val combinations = mutableSetOf<Double>()

        // Recursive function to calculate plate combinations
        fun combine(plates: List<Plate>, combination: List<Plate>, sum: Double) {
            if (combination.sumOf { it.thickness } <= barLength) {
                combinations.add(sum)
            }
            for (i in plates.indices) {
                combine(plates.subList(i + 1, plates.size), combination + plates[i], sum + plates[i].weight)
            }
        }

        combine(availablePlates, emptyList(), 0.0)
        return combinations.toSet()
    }
}
