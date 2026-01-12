package com.gabstra.myworkoutassistant.shared.utils

import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.max
import kotlin.math.min

data class WarmupContext(
    val isFirstExerciseInWorkout: Boolean,
    val muscleOverlapRatio: Double,
    val previousExerciseSameEquipment: Boolean,
    val isSupersetFollowUp: Boolean,
)

object WarmupPlanner {
    private data class WarmupProfile(
        val targetFractions: List<Double>,
        val repFractions: List<Double>,
        val capTotalWarmupReps: Int,
    )

    private fun resolveWarmupProfile(
        workReps: Int,
        maxWarmups: Int,
        capTotalWarmupReps: Int,
        context: WarmupContext?
    ): WarmupProfile {
        val baseCount = when {
            workReps <= 5 -> 4
            workReps <= 8 -> 3
            workReps <= 12 -> 3
            else -> 2
        }

        var count = baseCount.coerceAtMost(maxWarmups)
        if (context != null) {
            if (context.isFirstExerciseInWorkout) count += 1
            if (context.muscleOverlapRatio <= 0.2) count += 1
            if (context.muscleOverlapRatio >= 0.6) count -= 1
            if (context.previousExerciseSameEquipment) count -= 1
            if (context.isSupersetFollowUp) count -= 1
        }
        count = count.coerceIn(2, maxWarmups)

        return when (count) {
            4 -> WarmupProfile(
                targetFractions = listOf(0.0, 0.50, 0.75, 0.90),
                repFractions = listOf(0.66, 0.50, 0.33, 0.25),
                capTotalWarmupReps = min(25, capTotalWarmupReps)
            )
            3 -> WarmupProfile(
                targetFractions = listOf(0.0, 0.60, 0.80),
                repFractions = listOf(0.66, 0.50, 0.33),
                capTotalWarmupReps = min(20, capTotalWarmupReps)
            )
            else -> WarmupProfile(
                targetFractions = listOf(0.0, 0.70),
                repFractions = listOf(0.50, 0.33),
                capTotalWarmupReps = min(16, capTotalWarmupReps)
            )
        }
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
        baseAnchorTotal: Double? = null,
        convenienceStepKgTotal: Double? = null,
        capTotalWarmupReps: Int = 25,
        context: WarmupContext? = null,
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

        val profile = if (context != null) {
            resolveWarmupProfile(
                workReps = workReps,
                maxWarmups = maxWarmups,
                capTotalWarmupReps = capTotalWarmupReps,
                context = context
            )
        } else {
            null
        }

        val baseFractions = listOf(0.0, 0.50, 0.75, 0.90)
        val targetFractions = profile?.targetFractions ?: baseFractions

        val targets = targetFractions
            .map { f -> minVal + gap * f }
            .map { t -> floorToChoice(choices, t) ?: minVal }
            .filter { it < workWeight }
            .distinct()

        if (targets.isEmpty()) return emptyList()

        val selected = if (profile == null) targets.takeLast(maxWarmups) else targets

        val repFractions = profile?.repFractions ?: listOf(0.66, 0.50, 0.33, 0.25)
        fun repsFor(i: Int): Int {
            val f = repFractions.getOrElse(i) { repFractions.last() }
            return max(2, ceil(workReps * f).toInt())
        }

        val warmups = selected.mapIndexed { i, total -> total to repsFor(i) }.toMutableList()

        // Soft cap total warm-up reps by trimming earlier sets first (not below 2 reps)
        var sum = warmups.sumOf { it.second }
        val totalRepCap = profile?.capTotalWarmupReps ?: capTotalWarmupReps
        var k = 0
        while (sum > totalRepCap && k < warmups.size) {
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

    /**
     * Barbell-specific warm-up planner that optimizes weights to minimize plate changes
     * while staying close to desired work weight percentages.
     *
     * This function combines the percentage-based warm-up planning with plate change optimization
     * specifically for barbell exercises.
     *
     * @param availableTotals Feasible totals for the barbell (including bar weight), sorted
     * @param workWeight Planned working total (bar + plates)
     * @param workReps Target reps of the working set
     * @param barbell The barbell equipment instance
     * @param initialSetup List of plates already on one side of the bar before the first set
     * @param maxWarmups Maximum number of warm-up sets to generate
     * @param capTotalWarmupReps Soft cap on total warm-up reps
     * @param baseAnchorTotal Anchor to compute convenience steps from (e.g., 20.0 empty bar)
     * @param convenienceStepKgTotal If set (e.g., 5.0 for barbells = 2.5/side), keep only totals aligned to this step
     * @return List of optimized warm-up sets as (weight, reps) pairs
     */
    fun buildWarmupSetsForBarbell(
        availableTotals: Collection<Double>,
        workWeight: Double,
        workReps: Int,
        barbell: Barbell,
        initialSetup: List<Double> = emptyList(),
        maxWarmups: Int = 3,
        capTotalWarmupReps: Int = 25,
        baseAnchorTotal: Double? = null,
        convenienceStepKgTotal: Double? = null,
        context: WarmupContext? = null,
    ): List<Pair<Double, Int>> {
        // First, get initial warm-up targets based on work weight percentages
        val initialWarmups = buildWarmupSets(
            availableTotals = availableTotals,
            workWeight = workWeight,
            workReps = workReps,
            maxWarmups = maxWarmups,
            capTotalWarmupReps = capTotalWarmupReps,
            baseAnchorTotal = baseAnchorTotal,
            convenienceStepKgTotal = convenienceStepKgTotal,
            context = context,
        )

        // If no warm-ups were generated, return empty list
        if (initialWarmups.isEmpty()) return emptyList()

        // Optimize the warm-up weights to minimize plate changes
        return WarmupPlateOptimizer.optimizeBarbellWarmups(
            warmups = initialWarmups,
            availableTotals = availableTotals,
            workWeight = workWeight,
            barbell = barbell,
            initialSetup = initialSetup
        )
    }
}
