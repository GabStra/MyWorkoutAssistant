package com.gabstra.myworkoutassistant.shared.equipments

import java.util.UUID


abstract class WeightLoadedEquipment(
    id: UUID,
    type: EquipmentType,
    val extraWeights: List<BaseWeight> = emptyList(),
    val maxExtraWeightsPerLoadingPoint: Int = 0,
    private val loadingPoints: Int = 1
) : Equipment(id, type) {
    protected abstract fun getBaseCombinations(): Set<List<BaseWeight>>

    protected open fun isCombinationValid(combination: List<BaseWeight>): Boolean = true

    open fun getWeightsCombinationsWithLabels(): Set<Pair<Double, String>> {
        return getWeightsCombinations().map {
            it -> Pair(it, formatWeight(it))
        }.toSet()
    }

    open fun getWeightsCombinationsNoExtra(): Set<Double> {
        val baseCombinations = getBaseCombinations().filter { combo -> isCombinationValid(combo) }

        return baseCombinations
            .map{ combo -> combo.sumOf { it.weight*loadingPoints } }
            .filter { it != 0.0 }
            .sorted()
            .toSet()
    }

    open fun getWeightsCombinations(): Set<Double> {
        val baseCombinations = getBaseCombinations()
        val additionalCombinations = generateExtraWeightCombinations()
        val combinedCombinations = baseCombinations.flatMap { base ->
            additionalCombinations.map { additional -> base + additional }
        }.filter { combo -> isCombinationValid(combo) }

        return (baseCombinations + combinedCombinations)
            .map{ combo -> combo.sumOf { it.weight*loadingPoints } }
            .filter { it != 0.0 }
            .sorted()
            .toSet()
    }

    abstract fun formatWeight(weight: Double): String

    private fun generateExtraWeightCombinations(): Set<List<BaseWeight>> {
        val weights = mutableSetOf<List<BaseWeight>>()

        fun combine(availableWeights: List<BaseWeight>, combination: List<BaseWeight>) {
            if (combination.isNotEmpty() && combination.size <= maxExtraWeightsPerLoadingPoint && isCombinationValid(combination)) {
                weights.add(combination)
            }

            if(availableWeights.isEmpty() || combination.size > maxExtraWeightsPerLoadingPoint) {
                return
            }

            for (i in availableWeights.indices) {
                combine(availableWeights.subList(i + 1, availableWeights.size), combination + availableWeights[i])
            }
        }


        combine(extraWeights, emptyList())
        return weights
    }

    protected fun generateRecursiveValidSubsets(
        availableWeights: List<BaseWeight>
    ): Set<List<BaseWeight>> {
        val combinations = mutableSetOf<List<BaseWeight>>()

        fun combine(weights: List<BaseWeight>, combination: List<BaseWeight>) {
            if (combination.isNotEmpty() && isCombinationValid(combination)) {
                combinations.add(combination)
            }
            for (i in weights.indices) {
                combine(weights.subList(i + 1, weights.size), combination + weights[i])
            }
        }

        combine(availableWeights, emptyList())
        return combinations.toSet()
    }
}
