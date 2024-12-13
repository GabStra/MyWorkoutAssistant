package com.gabstra.myworkoutassistant.shared.utils

class PlateCalculator {
    companion object {
        data class PlateChange(
            val from: Double,
            val to: Double,
            val add: List<Double>,
            val remove: List<Double>
        )

        @JvmStatic
        fun calculatePlateChanges(
            plates: List<Double>,
            sets: List<Double>,
            barWeight: Double,
            initialSetup: List<Double> = emptyList()
        ): List<PlateChange> {
            val plateCounts = plates.groupingBy { it }.eachCount()

            val allCombos = sets.map { weight ->
                val needed = (weight - barWeight).coerceAtLeast(0.0)
                generateValidCombos(plateCounts, needed)
            }

            for (c in allCombos) {
                if (c.isEmpty()) {
                    throw IllegalArgumentException("No valid plate combination found for one of the target weights.")
                }
            }

            val n = sets.size
            val dp = Array(n) { DoubleArray(allCombos[it].size) { Double.POSITIVE_INFINITY } }
            val parent = Array(n) { IntArray(allCombos[it].size) { -1 } }

            // Initialize first set from the given initial setup instead of empty
            for (j in allCombos[0].indices) {
                dp[0][j] = countTotalChanges(initialSetup, allCombos[0][j])
            }

            // Fill DP for subsequent sets
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

            // Find minimal final solution
            var minCost = Double.POSITIVE_INFINITY
            var minIndex = -1
            for (j in allCombos[n - 1].indices) {
                if (dp[n - 1][j] < minCost) {
                    minCost = dp[n - 1][j]
                    minIndex = j
                }
            }

            // Reconstruct chosen combos
            val chosenCombos = mutableListOf<List<Double>>()
            var idx = minIndex
            for (i in (n - 1) downTo 0) {
                chosenCombos.add(allCombos[i][idx])
                idx = parent[i][idx]
            }
            chosenCombos.reverse()

            // Compute step-by-step changes
            val changes = mutableListOf<PlateChange>()
            var currentPlates = initialSetup
            for (i in sets.indices) {
                val requiredPlates = chosenCombos[i]
                val (toAdd, toRemove) = minimizeChanges(currentPlates, requiredPlates)
                changes.add(
                    PlateChange(
                        from = sumPlateWeights(currentPlates) + barWeight,
                        to = sets[i],
                        add = toAdd.sortedDescending(),
                        remove = toRemove.sortedDescending()
                    )
                )
                currentPlates = requiredPlates
            }

            return changes
        }

        private fun generateValidCombos(plateCounts: Map<Double, Int>, target: Double): List<List<Double>> {
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
                val pairValue = 2 * w
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
    }
}