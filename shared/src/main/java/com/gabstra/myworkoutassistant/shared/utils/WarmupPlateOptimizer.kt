package com.gabstra.myworkoutassistant.shared.utils

import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import kotlin.math.abs

object WarmupPlateOptimizer {

    private const val EPS = 1e-6
    private const val MAX_SEQUENCES_TO_EVALUATE = 250
    private const val ACCEPTABLE_COST_THRESHOLD = 2 // Early termination if we find a solution with cost <= this

    fun optimizeBarbellWarmups(
        warmups: List<Pair<Double, Int>>,
        availableTotals: Collection<Double>,
        workWeight: Double,
        barbell: Barbell,
        initialSetup: List<Double> = emptyList(),
        maxCandidatesPerSlot: Int = 10,
    ): List<Pair<Double, Int>> {
        if (warmups.isEmpty()) return warmups

        val achievableTotals = availableTotals
            .filter { it < workWeight - EPS }
            .sorted()

        if (achievableTotals.isEmpty()) return warmups

        val candidateLists = warmups.map { (target, _) ->
            val candidates = collectCandidates(target, achievableTotals, maxCandidatesPerSlot)
            candidates.ifEmpty { listOf(achievableTotals.first()) }
        }

        val plateInventory = barbell.availablePlates.map { it.weight }

        var bestSequence: List<Double>? = null
        var bestCost = Int.MAX_VALUE
        var bestDeviation = Double.POSITIVE_INFINITY
        var sequencesEvaluated = 0

        // Use greedy approach: evaluate sequences incrementally with early termination
        generateSequencesGreedy(
            candidateLists = candidateLists,
            plateInventory = plateInventory,
            workWeight = workWeight,
            barbell = barbell,
            initialSetup = initialSetup,
            warmups = warmups,
            onSequenceFound = { sequence, cost, deviation ->
                sequencesEvaluated++
                val isBetterCost = cost < bestCost
                val isSameCostBetterDeviation = cost == bestCost && deviation < bestDeviation - EPS

                if (isBetterCost || isSameCostBetterDeviation) {
                    bestCost = cost
                    bestDeviation = deviation
                    bestSequence = sequence
                }

                // Early termination: stop if we found a good enough solution
                // or if we've evaluated too many sequences
                cost <= ACCEPTABLE_COST_THRESHOLD || sequencesEvaluated >= MAX_SEQUENCES_TO_EVALUATE
            }
        )

        val chosen = bestSequence ?: return warmups

        return warmups.mapIndexed { index, (_, reps) -> chosen[index] to reps }
    }

    private fun collectCandidates(
        target: Double,
        totals: List<Double>,
        limit: Int
    ): List<Double> {
        if (totals.isEmpty() || limit <= 0) return emptyList()

        val sortedByDistance = totals
            .asSequence()
            .sortedBy { abs(it - target) }
            .take(limit * 2)
            .toList()

        if (sortedByDistance.isEmpty()) return emptyList()

        val dedup = linkedSetOf<Double>()
        for (value in sortedByDistance) {
            dedup += value
            if (dedup.size >= limit) break
        }

        return dedup.toList().sorted()
    }

    private fun generateSequencesGreedy(
        candidateLists: List<List<Double>>,
        plateInventory: List<Double>,
        workWeight: Double,
        barbell: Barbell,
        initialSetup: List<Double>,
        warmups: List<Pair<Double, Int>>,
        onSequenceFound: (List<Double>, Int, Double) -> Boolean // Returns true to stop early
    ) {
        val tolerance = 1e-4

        fun evaluateSequence(sequence: List<Double>): Pair<Int, Double>? {
            val totals = sequence + workWeight
            return try {
                val cost = PlateCalculator.calculatePlateChanges(
                    plateInventory,
                    totals,
                    barbell.barWeight,
                    initialSetup
                ).sumOf { it.change.steps.size }
                val deviation = totalDeviation(sequence, warmups)
                cost to deviation
            } catch (_: IllegalArgumentException) {
                null
            }
        }

        fun backtrack(
            index: Int,
            lastValue: Double,
            current: MutableList<Double>
        ): Boolean {
            if (index == candidateLists.size) {
                val result = evaluateSequence(current.toList()) ?: return false
                return onSequenceFound(current.toList(), result.first, result.second)
            }

            // Evaluate candidates in order (already sorted by deviation from target)
            // This greedy approach prioritizes sequences closest to target weights
            for (candidate in candidateLists[index]) {
                if (candidate <= lastValue + tolerance) continue

                current.add(candidate)
                val shouldStop = backtrack(index + 1, candidate, current)
                current.removeAt(current.lastIndex)
                
                if (shouldStop) return true
            }
            return false
        }

        backtrack(0, Double.NEGATIVE_INFINITY, mutableListOf())
    }

    private fun generateSequences(
        candidates: List<List<Double>>,
        index: Int,
        lastValue: Double,
        current: MutableList<Double>,
        output: MutableList<List<Double>>,
        tolerance: Double = 1e-4
    ) {
        if (index == candidates.size) {
            output += current.toList()
            return
        }

        for (candidate in candidates[index]) {
            if (candidate <= lastValue + tolerance) continue
            current.add(candidate)
            generateSequences(candidates, index + 1, candidate, current, output, tolerance)
            current.removeAt(current.lastIndex)
        }
    }

    private fun totalDeviation(sequence: List<Double>, original: List<Pair<Double, Int>>): Double {
        return sequence.indices.sumOf { abs(sequence[it] - original[it].first) }
    }
}

