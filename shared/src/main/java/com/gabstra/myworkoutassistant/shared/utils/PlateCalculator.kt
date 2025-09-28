package com.gabstra.myworkoutassistant.shared.utils

import kotlin.math.abs

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
         * @param sidesOnBarbell The number of sides to place plates on (typically 2).
         * @return A list of results, each containing the steps to transition from one set to the next.
         * @throws IllegalArgumentException if any target weight is impossible to achieve with the given plates.
         */
        @JvmStatic
        fun calculatePlateChanges(
            availablePlates: List<Double>,
            sets: List<Double>,
            barWeight: Double,
            initialPlates: List<Double> = emptyList(),
            sidesOnBarbell: UInt = 2u
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
                            val oldParent = parent[i][j]
                            val newReuse  = reuseScore(comboPrev, comboCurrent)
                            val oldReuse  = if (oldParent != -1) reuseScore(allCombos[i - 1][oldParent], comboCurrent) else -1

                            if (newReuse > oldReuse) {
                                parent[i][j] = k
                            } else if (newReuse == oldReuse) {
                                // Fallback: fewer plates in the previous state (your existing rule)
                                val oldBestPrevSize = if (oldParent != -1) allCombos[i - 1][oldParent].size else Int.MAX_VALUE
                                if (comboPrev.size < oldBestPrevSize) parent[i][j] = k
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

        private fun reuseScore(from: List<Double>, to: List<Double>): Int {
            val steps = generatePhysicalSteps(from, to)
            val removed = mutableMapOf<Double, Int>()
            val added = mutableMapOf<Double, Int>()
            for (s in steps) {
                when (s.action) {
                    Action.REMOVE -> removed[s.weight] = (removed[s.weight] ?: 0) + 1
                    Action.ADD    -> added[s.weight]   = (added[s.weight]   ?: 0) + 1
                }
            }
            var score = 0
            for ((w, a) in added) {
                val r = removed[w] ?: 0
                score += minOf(a, r)
            }
            return score
        }

        private fun generateValidCombos(
            plateCounts: Map<Double, Int>,
            targetTotalWeight: Double,
            sidesOnBarbell: UInt
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

                val weightOfOnePair = sidesOnBarbell.toDouble() * plateWeight

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

        private fun getTotalWeight(platesOnOneSide: List<Double>, barWeight: Double, sides: UInt): Double {
            val totalPlateWeight = platesOnOneSide.sumOf { it * sides.toDouble() }
            return barWeight + totalPlateWeight
        }

        fun generatePhysicalSteps(
            current: List<Double>,
            target: List<Double>
        ): List<PlateStep> {
            // Work with canonical inner→outer order (largest → smallest)
            val cur = current.sortedDescending().toMutableList()
            val tgt = target.sortedDescending()
            val steps = mutableListOf<PlateStep>()

            if (cur == tgt) return emptyList()

            while (true) {
                // Find first index where stacks differ (from inner to outer)
                var i = 0
                while (i < cur.size && i < tgt.size && cur[i] == tgt[i]) i++
                if (i >= cur.size && i >= tgt.size) break // done

                // 1) Expose index i by removing all outer plates beyond it
                while (cur.size > i + 1) {
                    val w = cur.removeAt(cur.lastIndex)
                    steps.add(PlateStep(Action.REMOVE, w))
                }

                val curHas = i < cur.size
                val tgtHas = i < tgt.size

                when {
                    // 2) Target has no plate here → remove the current plate at i
                    curHas && !tgtHas -> {
                        val w = cur.removeAt(cur.lastIndex) // i is now the last index
                        steps.add(PlateStep(Action.REMOVE, w))
                    }
                    // 3) Need to add a plate here → add target[i]
                    !curHas && tgtHas -> {
                        val w = tgt[i]
                        cur.add(w)
                        steps.add(PlateStep(Action.ADD, w))
                    }
                    // 4) Both have a plate here but they differ:
                    //    If current[i] is wrong (larger or smaller), remove it first.
                    curHas && tgtHas && cur[i] != tgt[i] -> {
                        val w = cur.removeAt(cur.lastIndex) // remove blocking/mismatched plate
                        steps.add(PlateStep(Action.REMOVE, w))
                    }
                }
            }

            return steps
        }

        @JvmStatic
        fun pickUniqueTotalsFromTotals(
            availablePlatesPerSide: List<Double>,   // PER-SIDE inventory (e.g., 5.0 listed 3 times ⇒ 3 pairs)
            achievableTotals: List<Double>,         // allowed totals (bar included), already filtered by constraints
            desiredTotals: List<Double>,            // targets (bar included)
            barWeight: Double,
            initialPlates: List<Double> = emptyList(),
            sidesOnBarbell: UInt = 2u
        ): List<Double> {
            require(desiredTotals.isNotEmpty()) { "desiredTotals is empty" }
            require(achievableTotals.isNotEmpty()) { "achievableTotals is empty" }

            val perSideCounts = availablePlatesPerSide.groupingBy { it }.eachCount()

            // Build combos for each achievable total (skip totals that end up impossible with given inventory)
            fun keyOf(x: Double) = "%.6f".format(x)
            val byTotalKey = linkedMapOf<String, Pair<Double, List<List<Double>>>>()
            for (t in achievableTotals) {
                val needPlateTotal = (t - barWeight).coerceAtLeast(0.0)
                val combos = generateValidCombosPerSideCounts(perSideCounts, needPlateTotal, sidesOnBarbell)
                if (combos.isNotEmpty()) byTotalKey[keyOf(t)] = t to combos.sortedBy { it.size } // prefer fewer plates within a total
            }
            require(byTotalKey.isNotEmpty()) { "No achievable total has a valid combo with the given inventory." }
            require(desiredTotals.size <= byTotalKey.size) {
                "Need ${desiredTotals.size} unique totals, only ${byTotalKey.size} achievable totals have valid combos."
            }

            data class Cand(val key: String, val total: Double, val combos: List<List<Double>>)
            // For each target: candidates sorted by closeness (primary objective)
            val perTarget: List<List<Cand>> = desiredTotals.map { target ->
                byTotalKey.entries
                    .asSequence()
                    .map { (k, v) -> Cand(k, v.first, v.second) }
                    .sortedBy { kotlin.math.abs(it.total - target) }
                    .toList()
            }

            data class Score(val err: Double, val plc: Int, val chg: Int) // err → plc → chg
            fun better(a: Score, b: Score, eps: Double = 1e-9): Boolean = when {
                a.err < b.err - eps -> true
                a.err > b.err + eps -> false
                a.plc < b.plc -> true
                a.plc > b.plc -> false
                a.chg < b.chg -> true
                a.chg > b.chg -> false
                else -> false
            }

            var best = Score(Double.POSITIVE_INFINITY, Int.MAX_VALUE, Int.MAX_VALUE)
            var bestPick: Array<Pair<Double, List<Double>>?> = arrayOfNulls(desiredTotals.size)

            fun search(
                i: Int,
                used: MutableSet<String>,
                prev: List<Double>,
                accErr: Double,
                accPlc: Int,
                accChg: Int,
                pick: Array<Pair<Double, List<Double>>?>
            ) {
                if (i == desiredTotals.size) {
                    val sc = Score(accErr, accPlc, accChg)
                    if (better(sc, best)) { best = sc; bestPick = pick.copyOf() }
                    return
                }

                // Branch & bound in order: err → plc → chg
                if (accErr > best.err) return
                if (kotlin.math.abs(accErr - best.err) < 1e-9 && accPlc > best.plc) return
                if (kotlin.math.abs(accErr - best.err) < 1e-9 && accPlc == best.plc && accChg > best.chg) return

                val want = desiredTotals[i]
                for (cand in perTarget[i]) {
                    if (cand.key in used) continue

                    // Choose combo within this total: minimize plates, then changes from prev
                    var combo = cand.combos[0]
                    var plc = combo.size
                    var chg = generatePhysicalSteps(prev, combo).size
                    for (c in cand.combos.asSequence().drop(1)) {
                        val plc2 = c.size
                        val chg2 = generatePhysicalSteps(prev, c).size
                        if (plc2 < plc || (plc2 == plc && chg2 < chg)) { combo = c; plc = plc2; chg = chg2 }
                    }

                    val newErr = accErr + kotlin.math.abs(cand.total - want)
                    val newPlc = accPlc + plc
                    val newChg = accChg + chg

                    used += cand.key
                    pick[i] = cand.total to combo
                    search(i + 1, used, combo, newErr, newPlc, newChg, pick)
                    used.remove(cand.key)
                    pick[i] = null
                }
            }

            search(0, mutableSetOf(), initialPlates, 0.0, 0, 0, arrayOfNulls(desiredTotals.size))
            check(bestPick.all { it != null }) { "No unique assignment found with the given achievableTotals." }
            return bestPick.map { it!!.first } // unique totals in order
        }

        /** Build combos when available plates are PER-SIDE counts (i.e., count = number of pairs available). */
        private fun generateValidCombosPerSideCounts(
            plateCountsPerSide: Map<Double, Int>,
            targetTotalPlateWeight: Double,   // (desiredTotal - barWeight) across BOTH sides
            sidesOnBarbell: UInt
        ): List<List<Double>> {
            if (kotlin.math.abs(targetTotalPlateWeight) < 1e-9) return listOf(emptyList())
            val results = mutableSetOf<List<Double>>()
            val weights = plateCountsPerSide.keys.sortedDescending()
            val sides = sidesOnBarbell.toDouble()

            fun backtrack(idx: Int, oneSide: MutableList<Double>, curTotal: Double) {
                if (kotlin.math.abs(curTotal - targetTotalPlateWeight) < 1e-9) {
                    results.add(oneSide.sortedDescending())
                    return
                }
                if (curTotal > targetTotalPlateWeight + 1e-9 || idx >= weights.size) return

                val w = weights[idx]
                val maxPairs = plateCountsPerSide.getValue(w)     // PER-SIDE count == number of pairs available
                val pairTotal = sides * w                         // total contribution (both sides) of one pair

                // skip this weight
                backtrack(idx + 1, oneSide, curTotal)

                // use 1..maxPairs pairs
                for (pairs in 1..maxPairs) {
                    val newTotal = curTotal + pairs * pairTotal
                    if (newTotal > targetTotalPlateWeight + 1e-9) break
                    repeat(pairs) { oneSide.add(w) }              // record ONE-SIDE stack; symmetry implied
                    backtrack(idx + 1, oneSide, newTotal)
                    repeat(pairs) { oneSide.removeAt(oneSide.lastIndex) }
                }
            }

            backtrack(0, mutableListOf(), 0.0)
            return results.toList().sortedBy { it.size }          // fewer plates preferred
        }

    }
}