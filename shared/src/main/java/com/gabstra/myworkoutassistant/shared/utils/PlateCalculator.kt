package com.gabstra.myworkoutassistant.shared.utils

import android.util.Log

class PlateCalculator {
    companion object {
        enum class Action {
            ADD, REMOVE
        }

        data class PlateStep(
            val action: Action,  // "add" or "remove"
            val weight: Double,
        )

        data class PlateChange(
            val from: Double,
            val to: Double,
            val steps: List<PlateStep>
        )

        data class PlateChangeResult(
            val change: PlateChange,
            val currentPlates: List<Double>
        )

        @JvmStatic
        fun calculatePlateChanges(
            plates: List<Double>,
            sets: List<Double>,
            barWeight: Double,
            initialSetup: List<Double> = emptyList(),
            multiplier: Double = 2.0
        ): List<PlateChangeResult>  {
            // Keep the existing plate combination calculation logic
            val plateCounts = plates.groupingBy { it }.eachCount()
            val allCombos = sets.map { weight ->
                val needed = (weight - barWeight).coerceAtLeast(0.0)
                generateValidCombos(plateCounts, needed,multiplier)
            }

            if(allCombos.isEmpty()) {
                return emptyList()
            }

            // Validation check
            for (c in allCombos) {
                if (c.isEmpty()) {
                    return emptyList()
                }
            }

            // Use the existing DP logic to find optimal plate combinations
            val n = sets.size
            val dp = Array(n) { DoubleArray(allCombos[it].size) { Double.POSITIVE_INFINITY } }
            val parent = Array(n) { IntArray(allCombos[it].size) { -1 } }

            for (j in allCombos[0].indices) {
                dp[0][j] = countTotalChanges(initialSetup, allCombos[0][j])
            }

            for (i in 1 until n) {
                for (j in allCombos[i].indices) {
                    val comboCurrent = allCombos[i][j]
                    for (k in allCombos[i - 1].indices) {
                        val comboPrev = allCombos[i - 1][k]
                        val cost = dp[i - 1][k] + countTotalChanges(comboPrev, comboCurrent)

                        // Case 1: This cost is better than current cost
                        if (cost < dp[i][j]) {
                            dp[i][j] = cost
                            parent[i][j] = k
                        }
                        // Case 2: Same cost but need to compare sizes
                        else if (cost == dp[i][j]) {
                            // Get size of current best combo if parent exists
                            val currentBestComboSize = if (parent[i][j] != -1) {
                                allCombos[i-1][parent[i][j]].size  // Changed from allCombos[i][parent[i][j]].size
                            } else {
                                Int.MAX_VALUE // If no parent, assume infinite size
                            }

                            // Update if new combo has smaller size
                            if (comboPrev.size < currentBestComboSize) {  // Changed from comboCurrent.size
                                dp[i][j] = cost
                                parent[i][j] = k
                            }
                        }
                    }
                }
            }

            // Find optimal solution
            var minCost = Double.POSITIVE_INFINITY
            var minIndex = -1
            for (j in allCombos[n - 1].indices) {
                if (dp[n - 1][j] < minCost) {
                    minCost = dp[n - 1][j]
                    minIndex = j
                }
            }

            if (minIndex == -1) {
                return emptyList()
            }

            // Reconstruct chosen combinations
            val chosenCombos = mutableListOf<List<Double>>()
            var idx = minIndex
            for (i in (n - 1) downTo 0) {
                chosenCombos.add(allCombos[i][idx])
                if (parent[i][idx] == -1 && i > 0) {
                    // If we hit a -1 parent but still have sets to process,
                    // there's a disconnection in the optimal path
                    return emptyList()
                }
                if (i > 0) {
                    idx = parent[i][idx]
                }
            }
            chosenCombos.reverse()

            // Generate step-by-step changes with physical constraints
            val results = mutableListOf<PlateChangeResult>()
            var currentPlates = initialSetup
            for (i in sets.indices) {
                val targetPlates = chosenCombos[i]
                val physicalSteps = generatePhysicalSteps(currentPlates.sortedDescending(), targetPlates.sortedDescending())

                results.add(
                    PlateChangeResult(
                        PlateChange(
                            from = sumPlateWeights(currentPlates) + barWeight,
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

        private fun generateValidCombos(plateCounts: Map<Double, Int>, target: Double,multiplier: Double): List<List<Double>> {
            if (target == 0.0) return listOf(emptyList())

            val results = mutableListOf<List<Double>>()
            val uniqueWeights = plateCounts.keys.sortedDescending()
            val counts = plateCounts.toMutableMap()

            fun backtrack(i: Int, currentCombo: MutableList<Double>, currentSum: Double) {
                if (currentSum == target) {
                    val comboSorted = currentCombo.sorted()
                    if (comboSorted !in results) {
                        results.add(comboSorted)
                    }
                    return
                }
                if (currentSum > target || i >= uniqueWeights.size) return

                // Skip this weight
                backtrack(i + 1, currentCombo, currentSum)

                // Try using pairs of this weight
                val w = uniqueWeights[i]
                val pairValue = multiplier * w
                val maxPairs = counts[w] ?: 0
                for (usePairs in 1..maxPairs) {
                    val newSum = currentSum + usePairs * pairValue
                    if (newSum > target) break
                    repeat(usePairs) { currentCombo.add(w) }
                    backtrack(i + 1, currentCombo, newSum)
                    repeat(usePairs) { currentCombo.removeAt(currentCombo.lastIndex) }
                }
            }

            backtrack(0, mutableListOf(), 0.0)
            return results.sortedBy { it.size }
        }

        private fun minimizeChanges(currentPlates: List<Double>, requiredPlates: List<Double>): Pair<List<Double>, List<Double>> {
            val currentCount = currentPlates.groupingBy { it }.eachCount()
            val requiredCount = requiredPlates.groupingBy { it }.eachCount()

            val toRemove = mutableListOf<Double>()
            val toAdd = mutableListOf<Double>()

            for ((plate, count) in currentCount) {
                val diff = count - (requiredCount[plate] ?: 0)
                if (diff > 0) {
                    repeat(diff) { toRemove.add(plate) }
                }
            }

            for ((plate, count) in requiredCount) {
                val diff = count - (currentCount[plate] ?: 0)
                if (diff > 0) {
                    repeat(diff) { toAdd.add(plate) }
                }
            }

            return Pair(toAdd, toRemove)
        }

        private fun countTotalChanges(a: List<Double>, b: List<Double>): Double {
            val (toAdd, toRemove) = minimizeChanges(a, b)
            return (toAdd.size + toRemove.size).toDouble()
        }

        private fun sumPlateWeights(plates: List<Double>): Double {
            // Each entry in plates represents a pair weight, so total = sum of 2*w for each w
            return plates.sumOf { it * 2 }
        }

        fun generatePhysicalSteps(currentPlates: List<Double>, targetPlates: List<Double>): List<PlateStep> {
            val steps = mutableListOf<PlateStep>()

            // If current is empty, just add all target plates
            if (currentPlates.isEmpty()) {
                targetPlates.forEach { plate ->
                    steps.add(PlateStep(Action.ADD, plate))
                }
                return steps
            }

            // If both configs are the same, no steps needed
            if (currentPlates == targetPlates) {
                return steps
            }

            var i = 0
            while (i < currentPlates.size && i < targetPlates.size) {
                if (currentPlates[i] != targetPlates[i]) {
                    // Found mismatch, need to remove from here until we find a matching sequence
                    var matchPoint = i
                    // Look for a point where sequences match again
                    while (matchPoint < currentPlates.size && matchPoint < targetPlates.size) {
                        if (currentPlates[matchPoint] == targetPlates[matchPoint]) {
                            var allMatch = true
                            // Verify all subsequent plates match
                            for (j in matchPoint until minOf(currentPlates.size, targetPlates.size)) {
                                if (currentPlates[j] != targetPlates[j]) {
                                    allMatch = false
                                    break
                                }
                            }
                            if (allMatch) break
                        }
                        matchPoint++
                    }

                    // Remove plates from i to matchPoint
                    for (j in currentPlates.size - 1 downTo i) {
                        steps.add(PlateStep(Action.REMOVE, currentPlates[j]))
                    }
                    // Add new plates
                    for (j in i until targetPlates.size) {
                        steps.add(PlateStep(Action.ADD, targetPlates[j]))
                    }
                    break
                }
                i++
            }

            // Handle case where current is longer than target
            if (i == targetPlates.size && i < currentPlates.size) {
                for (j in currentPlates.size - 1 downTo i) {
                    steps.add(PlateStep(Action.REMOVE, currentPlates[j]))
                }
            }

            // Handle case where target is longer than current
            if (i == currentPlates.size && i < targetPlates.size) {
                for (j in i until targetPlates.size) {
                    steps.add(PlateStep(Action.ADD, targetPlates[j]))
                }
            }

            return steps
        }
    }
}