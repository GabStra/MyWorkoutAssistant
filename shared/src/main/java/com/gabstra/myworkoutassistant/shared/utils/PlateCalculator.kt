package com.gabstra.myworkoutassistant.shared.utils

import kotlin.math.abs
import kotlin.math.min

class PlateCalculator {
    companion object {
        enum class Action {
            ADD, REMOVE
        }

        data class PlateStep(
            val action: Action,
            val weight: Double,
        )

        data class PlateChange(
            val from: Double,
            val to: Double,
            val steps: List<PlateStep>
        )

        data class PlateChangeResult(
            val change: PlateChange,
            val currentPlates: List<Double> // Plates on one side of the bar
        )

        /**
         * Calculates the most efficient sequence of plate changes for a series of weights.
         *
         * @param availablePlates The list of all available plates (e.g., [20.0, 20.0, 10.0, 5.0, 5.0]).
         * @param sets The list of target total weights for each set (e.g., [100.0, 120.0, 100.0]).
         * @param barWeight The weight of the barbell itself.
         * @param initialPlates The list of plates already on one side of the bar before the first set.
         * @param sidesOnBarbell The number of sides to place plates on (typically 2.0).
         * @return A list of results, each containing the steps to transition from one set to the next.
         * @throws IllegalArgumentException if any target weight is impossible to achieve with the given plates.
         */
        @JvmStatic
        fun calculatePlateChanges(
            availablePlates: List<Double>,
            sets: List<Double>,
            barWeight: Double,
            initialPlates: List<Double> = emptyList(),
            sidesOnBarbell: Double = 2.0
        ): List<PlateChangeResult> {
            val plateCounts = availablePlates.groupingBy { it }.eachCount()

            // For each target weight, find all possible ways to make that weight with the available plates.
            val allCombos = sets.map { weight ->
                val neededPlateWeight = (weight - barWeight).coerceAtLeast(0.0)
                generateValidCombos(plateCounts, neededPlateWeight, sidesOnBarbell)
            }

            // BEST OF BOTH: Use exception handling for impossible states.
            if (allCombos.any { it.isEmpty() }) {
                throw IllegalArgumentException("Impossible to find a valid plate combination for one or more target weights with the available plates.")
            }

            val n = sets.size
            if (n == 0) return emptyList()

            // DP table to store the minimum cost (number of changes) to reach set `i` with combination `j`.
            val dp = Array(n) { DoubleArray(allCombos[it].size) { Double.POSITIVE_INFINITY } }
            // Parent table to reconstruct the optimal path.
            val parent = Array(n) { IntArray(allCombos[it].size) { -1 } }

            // Initialize DP table for the first set. Cost is changes from the initial setup.
            for (j in allCombos[0].indices) {
                dp[0][j] = countTotalChanges(initialPlates, allCombos[0][j])
            }

            // Fill DP table for all subsequent sets.
            for (i in 1 until n) {
                for (j in allCombos[i].indices) {
                    val comboCurrent = allCombos[i][j]
                    for (k in allCombos[i - 1].indices) {
                        val comboPrev = allCombos[i - 1][k]
                        val cost = dp[i - 1][k] + countTotalChanges(comboPrev, comboCurrent)

                        if (cost < dp[i][j]) {
                            dp[i][j] = cost
                            parent[i][j] = k
                        } else if (cost == dp[i][j]) {
                            // CORRECT TIE-BREAKER: Prefer path from a previous state with fewer plates.
                            val oldBestPrevComboSize = if (parent[i][j] != -1) allCombos[i - 1][parent[i][j]].size else Int.MAX_VALUE
                            if (comboPrev.size < oldBestPrevComboSize) {
                                parent[i][j] = k
                            }
                        }
                    }
                }
            }

            // Find the optimal combination for the final set.
            val minIndex = dp[n - 1].indices.minByOrNull { dp[n - 1][it] }
                ?: throw IllegalStateException("Failed to find an optimal path despite valid combinations. This indicates an algorithm error.")


            // Reconstruct the optimal path by backtracking through the parent table.
            val chosenCombos = mutableListOf<List<Double>>()
            var currentIdx = minIndex
            for (i in (n - 1) downTo 0) {
                chosenCombos.add(allCombos[i][currentIdx])
                currentIdx = parent[i][currentIdx]
            }
            chosenCombos.reverse()

            // Generate the final results with human-readable physical steps for each transition.
            val results = mutableListOf<PlateChangeResult>()
            var currentPlates = initialPlates
            for (i in sets.indices) {
                val targetPlates = chosenCombos[i]
                val physicalSteps = generatePhysicalSteps(currentPlates, targetPlates)

                results.add(
                    PlateChangeResult(
                        PlateChange(
                            from = getTotalWeight(currentPlates, barWeight, sidesOnBarbell),
                            to = sets[i],
                            steps = physicalSteps
                        ),
                        targetPlates
                    )
                )
                currentPlates = targetPlates
            }

            return results
        }

        private fun generateValidCombos(
            plateCounts: Map<Double, Int>,
            targetTotalWeight: Double,
            sidesOnBarbell: Double
        ): List<List<Double>> {

            if (abs(targetTotalWeight) < 1e-9) return listOf(emptyList())

            val resultsSet = mutableSetOf<List<Double>>()
            val uniqueWeights = plateCounts.keys.sortedDescending()

            fun backtrack(comboIndex: Int, platesForOneSide: MutableList<Double>, currentTotalWeight: Double) {

                if (abs(currentTotalWeight - targetTotalWeight) < 1e-9) {
                    resultsSet.add(platesForOneSide.sortedDescending())
                    return
                }
                if (currentTotalWeight > targetTotalWeight || comboIndex >= uniqueWeights.size) return

                val plateWeight = uniqueWeights[comboIndex]
                val availableCount = plateCounts.getValue(plateWeight)
                val weightOfOnePair = sidesOnBarbell * plateWeight

                // Option 1: Skip this plate weight and move to the next.
                backtrack(comboIndex + 1, platesForOneSide, currentTotalWeight)

                // Option 2: Use one or more pairs of this plate weight.
                for (pairsToUse in 1..availableCount) {
                    val newTotalWeight = currentTotalWeight + pairsToUse * weightOfOnePair
                    if (newTotalWeight > targetTotalWeight + 1e-9) break

                    repeat(pairsToUse) { platesForOneSide.add(plateWeight) }
                    backtrack(comboIndex + 1, platesForOneSide, newTotalWeight)
                    repeat(pairsToUse) { platesForOneSide.removeAt(platesForOneSide.lastIndex) }
                }
            }

            backtrack(0, mutableListOf(), 0.0)
            return resultsSet.toList().sortedBy { it.size }
        }

        private fun minimizeChanges(
            currentPlates: List<Double>,
            targetPlates: List<Double>
        ): Pair<List<Double>, List<Double>> {
            val currentCount = currentPlates.groupingBy { it }.eachCount()
            val targetCount = targetPlates.groupingBy { it }.eachCount()
            val allPlateWeights = (currentCount.keys + targetCount.keys)

            val toAdd = mutableListOf<Double>()
            val toRemove = mutableListOf<Double>()

            for (plate in allPlateWeights) {
                val currentNum = currentCount[plate] ?: 0
                val targetNum = targetCount[plate] ?: 0
                when {
                    targetNum > currentNum -> repeat(targetNum - currentNum) { toAdd.add(plate) }
                    currentNum > targetNum -> repeat(currentNum - targetNum) { toRemove.add(plate) }
                }
            }
            return Pair(toAdd, toRemove)
        }

        private fun countTotalChanges(a: List<Double>, b: List<Double>): Double {
            return generatePhysicalSteps(a, b).size.toDouble()
        }

        private fun getTotalWeight(platesOnOneSide: List<Double>, barWeight: Double, sides: Double): Double {
            val totalPlateWeight = platesOnOneSide.sumOf { it * sides }
            return barWeight + totalPlateWeight
        }

        /**
         * Generates a sequence of physical steps (add/remove) to transition between plate configurations.
         * This respects the physical constraint that outer plates must be removed first.
         */
        fun generatePhysicalSteps(
            current: List<Double>,
            target: List<Double>
        ): List<PlateStep> {
            val sortedCurrent = current.sortedDescending()
            val sortedTarget  = target.sortedDescending()
            if (sortedCurrent == sortedTarget) return emptyList()

            // base diff
            val (toAdd, toRemove) = minimizeChanges(sortedCurrent, sortedTarget)

            // biggest new plate
            val maxNew = toAdd.maxOrNull() ?: 0.0

            // temporary removes (lighter than maxNew, but not in toRemove)
            val tempRemove = sortedCurrent.filter { it < maxNew && !toRemove.contains(it) }

            val removalSeq = (tempRemove + toRemove).sorted()

            val reAdd = tempRemove
                .distinct()
                .flatMap { p ->
                    val cntTemp   = tempRemove.count { it == p }
                    val cntTarget = sortedTarget.count  { it == p }
                    List(min(cntTemp, cntTarget)) { p }
                }

            var toAddAndReAdd = toAdd + reAdd
            toAddAndReAdd = toAddAndReAdd.sortedDescending()

            return buildList {
                removalSeq.forEach { add(PlateStep(Action.REMOVE, it)) }
                toAddAndReAdd    .forEach { add(PlateStep(Action.ADD,    it)) }
            }
        }
    }
}