package com.gabstra.myworkoutassistant.shared.utils

import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import kotlin.math.abs

object WarmupPlateOptimizer {

    private const val EPS = 1e-6

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

        val sequences = mutableListOf<List<Double>>()
        generateSequences(candidateLists, 0, Double.NEGATIVE_INFINITY, mutableListOf(), sequences)
        if (sequences.isEmpty()) return warmups

        val plateInventory = barbell.availablePlates.map { it.weight }

        var bestSequence: List<Double>? = null
        var bestCost = Int.MAX_VALUE
        var bestDeviation = Double.POSITIVE_INFINITY

        for (sequence in sequences) {
            val totals = sequence + workWeight

            val cost = try {
                PlateCalculator.calculatePlateChanges(
                    plateInventory,
                    totals,
                    barbell.barWeight,
                    initialSetup
                ).sumOf { it.change.steps.size }
            } catch (_: IllegalArgumentException) {
                continue
            }

            val deviation = totalDeviation(sequence, warmups)
            val isBetterCost = cost < bestCost
            val isSameCostBetterDeviation = cost == bestCost && deviation < bestDeviation - EPS

            if (isBetterCost || isSameCostBetterDeviation) {
                bestCost = cost
                bestDeviation = deviation
                bestSequence = sequence
            }
        }

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

