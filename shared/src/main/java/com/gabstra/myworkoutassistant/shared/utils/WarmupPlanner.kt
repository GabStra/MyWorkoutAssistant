package com.gabstra.myworkoutassistant.shared.utils

import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.max

object WarmupPlanner {

    fun buildWarmupSetsBestStep(
        availableTotals: Collection<Double>,
        workWeight: Double,
        workReps: Int,
        baseAnchorTotal: Double = 0.0,
        candidateStepsDesc: List<Double> = listOf(10.0, 5.0, 2.5, 1.0, 0.5, 0.25),
        includeNoStep: Boolean = true,
        maxWarmups: Int = 3,
        capTotalWarmupReps: Int = 25,
    ): List<Pair<Double, Int>> {
        val steps = candidateStepsDesc.filter { it > 0.0 }.distinct().sortedDescending()

        val candidates = mutableListOf<Pair<Double?, List<Pair<Double, Int>>>>()


        for (step in steps) {
            val sets = buildWarmupSets(
                availableTotals = availableTotals,
                workWeight = workWeight,
                workReps = workReps,
                maxWarmups = maxWarmups,
                capTotalWarmupReps = capTotalWarmupReps,
                convenienceStepKgTotal = step,
                baseAnchorTotal = baseAnchorTotal
            )
            candidates += step to sets
        }

        // Optionally try with no convenience step
        if (includeNoStep) {
            val setsNoStep = buildWarmupSets(
                availableTotals = availableTotals,
                workWeight = workWeight,
                workReps = workReps,
                maxWarmups = maxWarmups,
                capTotalWarmupReps = capTotalWarmupReps,
                convenienceStepKgTotal = null,
                baseAnchorTotal = baseAnchorTotal
            )
            candidates += (null to setsNoStep)
        }

        // Pick the candidate with:
        // 1) max number of sets, 2) highest convenience step (null treated as -∞)
        val best = candidates.maxWithOrNull(Comparator { a, b ->
            val countCmp = a.second.size.compareTo(b.second.size)
            if (countCmp != 0) countCmp
            else {
                val sa = a.first ?: Double.NEGATIVE_INFINITY
                val sb = b.first ?: Double.NEGATIVE_INFINITY
                sa.compareTo(sb)
            }
        })

        return best?.second ?: emptyList()
    }

    /**
     * Gap-based warm-up planner (device-agnostic) with optional barbell-style convenience filtering.
     *
     * Inputs are TOTALS (already include bar/handles or BW for bodyweight work):
     * - availableTotals: feasible totals for the implement, sorted (e.g., [BW, BW+1, ...] or [20, 25, 30, ...]).
     * - workWeight: planned working total (already BW+extra, or bar+plates, etc.).
     * - workReps: target reps of the working set.
     *
     * Options:
     * - convenienceStepKgTotal: if set (e.g., 5.0 for barbells = 2.5/side), keep only totals aligned to this step from the anchor.
     * - baseAnchorTotal: anchor to compute convenience steps from (e.g., 20.0 empty bar). Defaults to the minimal feasible total < work.
     *
     * Policy:
     * - Choose up to [maxWarmups] checkpoints strictly below work, at ~0%, 50%, 75% (and optional 90%) of the gap.
     * - Snap each checkpoint DOWN to the nearest feasible total.
     * - Taper reps as fractions of work reps (≈⅔ → ½ → ⅓ → ¼), min 2 reps.
     * - Soft cap on total warm-up reps.
     */
    fun buildWarmupSets(
        availableTotals: Collection<Double>,
        workWeight: Double,
        workReps: Int,
        maxWarmups: Int = 3,
        baseAnchorTotal: Double?,
        convenienceStepKgTotal: Double?,
        capTotalWarmupReps: Int = 25,
    ): List<Pair<Double, Int>> {
        if (availableTotals.isEmpty()) return emptyList()


        val choicesRaw = availableTotals
            .filter { it < workWeight }
            .distinct()
            .sorted()
        if (choicesRaw.isEmpty()) return emptyList()

        val anchor = baseAnchorTotal ?: choicesRaw.first()

        // Optional barbell-style convenience filter (e.g., 5 kg total jumps)
        val choices = if (convenienceStepKgTotal != null && convenienceStepKgTotal > 0.0) {
            val tol = 0.125 // kg tolerance for float rounding
            val filtered = choicesRaw.filter { isMultipleOfStep(anchor, it, convenienceStepKgTotal, tol) }
            if (filtered.size >= 2) filtered else choicesRaw // fall back if too aggressive
        } else {
            choicesRaw
        }

        val minVal = choices.first()
        val gap = (workWeight - minVal).coerceAtLeast(0.0)

        val baseFractions = mutableListOf(0.0, 0.50, 0.75, 0.90)

        val targets = baseFractions
            .map { f -> minVal + gap * f }
            .map { t -> floorToChoice(choices, t) ?: minVal }
            .filter { it < workWeight }
            .distinct()

        if (targets.isEmpty()) return emptyList()

        val selected = targets.takeLast(maxWarmups)

        val repFractions = listOf(0.66, 0.50, 0.33, 0.25)
        fun repsFor(i: Int): Int {
            val f = repFractions.getOrElse(i) { 0.25 }
            return max(2, ceil(workReps * f).toInt())
        }

        val warmups = selected.mapIndexed { i, total -> total to repsFor(i) }.toMutableList()

        // Soft cap total warm-up reps by trimming earlier sets first (not below 2 reps)
        var sum = warmups.sumOf { it.second }
        var k = 0
        while (sum > capTotalWarmupReps && k < warmups.size) {
            val (w, r) = warmups[k]
            val newR = max(2, r - 1)
            if (newR < r) {
                warmups[k] = w to newR
                sum--
            } else {
                k++
            }
        }

        return warmups
    }

    private fun isMultipleOfStep(anchor: Double, value: Double, step: Double, tol: Double): Boolean {
        val diff = value - anchor
        if (diff < -tol) return false
        val rem = diff % step
        return abs(rem) <= tol || abs(rem - step) <= tol
    }

    private fun floorToChoice(choices: List<Double>, target: Double): Double? {
        var lo = 0
        var hi = choices.lastIndex
        var ans: Double? = null
        while (lo <= hi) {
            val mid = (lo + hi) ushr 1
            val v = choices[mid]
            if (v <= target) { ans = v; lo = mid + 1 } else hi = mid - 1
        }
        return ans
    }
}
