package com.gabstra.myworkoutassistant.shared.equipments

import java.util.UUID

abstract class Equipment(
    val id : UUID,
    val additionalPlates: List<Plate>,
    val maxAdditionalItems: Int,
    val type: EquipmentType
) {
    abstract val name: String

    // Abstract function for base combinations (specific to Dumbbell/Barbell)
    protected abstract fun calculateBaseCombinations(): Set<Double>

    // Optional validation for specific constraints (e.g., barbell length)
    protected open fun isCombinationValid(combination: List<Plate>): Boolean = true

    // Generate possible combinations
    fun calculatePossibleCombinations(): Set<Double> {
        val baseCombinations = calculateBaseCombinations()
        val additionalCombinations = generateAdditionalPlateCombinations()
        val combinedCombinations = baseCombinations.flatMap { base ->
            additionalCombinations.map { additional -> base + additional }
        }
        return (baseCombinations + combinedCombinations).sorted().toSet()
    }

    // Generate all valid combinations of additional plates
    private fun generateAdditionalPlateCombinations(): Set<Double> {
        val weights = mutableSetOf<Double>()

        fun combine(plates: List<Plate>, combination: List<Plate>, sum: Double) {
            if (combination.size <= maxAdditionalItems && isCombinationValid(combination)) {
                weights.add(sum)
            }
            if (combination.size >= maxAdditionalItems) return

            for (i in plates.indices) {
                combine(plates.subList(i + 1, plates.size), combination + plates[i], sum + plates[i].weight)
            }
        }

        combine(additionalPlates, emptyList(), 0.0)
        return weights
    }
}
