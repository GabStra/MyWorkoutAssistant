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

        @JvmStatic
        fun calculatePlateChanges(
            plates: List<Double>,
            sets: List<Double>,
            barWeight: Double,
            initialSetup: List<Double> = emptyList(),
            multiplier: Double = 2.0
        ): List<PlateChange> {
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
                    throw IllegalArgumentException("No valid plate combination found for one of the target weights.")
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
                        if (cost < dp[i][j]) {
                            dp[i][j] = cost
                            parent[i][j] = k
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

            // Reconstruct chosen combinations
            val chosenCombos = mutableListOf<List<Double>>()
            var idx = minIndex
            for (i in (n - 1) downTo 0) {
                chosenCombos.add(allCombos[i][idx])
                idx = parent[i][idx]
            }
            chosenCombos.reverse()

            // Generate step-by-step changes with physical constraints
            val changes = mutableListOf<PlateChange>()
            var currentPlates = initialSetup
            for (i in sets.indices) {
                val targetPlates = chosenCombos[i]
                val physicalSteps = generatePhysicalSteps(currentPlates, targetPlates)

                changes.add(
                    PlateChange(
                        from = sumPlateWeights(currentPlates) + barWeight,
                        to = sets[i],
                        steps = physicalSteps
                    )
                )
                currentPlates = targetPlates
            }

            return changes
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
            return results
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

        private fun generatePhysicalSteps(
            currentPlates: List<Double>,
            targetPlates: List<Double>
        ): List<PlateStep> {
            val steps = mutableListOf<PlateStep>()

            // Handle empty configurations
            if (currentPlates.isEmpty() && targetPlates.isEmpty()) {
                return steps
            }

            if (currentPlates.isEmpty()) {
                return targetPlates.sortedDescending().map {
                    PlateStep(Action.ADD, it)
                }
            }

            if (targetPlates.isEmpty()) {
                return currentPlates.sortedDescending().reversed().map {
                    PlateStep(Action.REMOVE, it)
                }
            }

            // Convert to lists ordered from inner to outer
            val current = currentPlates.sortedDescending()
            val target = targetPlates.sortedDescending()

            // Find common prefix (plates that don't need to be touched)
            var commonPrefix = 0
            while (commonPrefix < minOf(current.size, target.size) &&
                current[commonPrefix] == target[commonPrefix]) {
                commonPrefix++
            }

            // If configurations are identical, return empty steps
            if (commonPrefix == current.size && commonPrefix == target.size) {
                return steps
            }

            // Track plates that need to be temporarily removed and replaced
            val platesToRestore = mutableListOf<Double>()
            val seenPlates = mutableMapOf<Double, Int>() // Track count of each plate weight

            // 1. Remove outer plates from point of difference
            for (i in current.lastIndex downTo commonPrefix) {
                val plate = current[i]
                if (target.contains(plate)) {
                    val targetCount = target.count { it == plate }
                    val currentCount = seenPlates.getOrDefault(plate, 0)
                    if (currentCount < targetCount) {
                        platesToRestore.add(0, plate)
                        seenPlates[plate] = currentCount + 1
                    }
                }
                steps.add(PlateStep(Action.REMOVE, plate))
            }

            // 2. Add new plates that aren't being restored
            for (i in commonPrefix until target.size) {
                val plate = target[i]
                if (!platesToRestore.contains(plate) ||
                    platesToRestore.count { it == plate } < target.count { it == plate }) {
                    steps.add(PlateStep(Action.ADD, plate))
                }
            }

            // 3. Restore the saved plates in correct order
            platesToRestore.forEach { plate ->
                steps.add(PlateStep(Action.ADD, plate))
            }

            return steps
        }
    }
}