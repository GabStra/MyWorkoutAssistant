package com.gabstra.myworkoutassistant.shared.utils

import kotlin.math.roundToInt

/**
 * Hydration helpers derived from already-collected workout signals.
 */
object HydrationEstimation {

    private const val REPLACEMENT_FACTOR = 1.25

    /**
     * Sweat replacement target: 125% of measured fluid loss, rounded to the
     * nearest millilitre. Negative losses are clamped to zero.
     */
    fun replacementTargetMl(lossMl: Int): Int =
        (lossMl * REPLACEMENT_FACTOR).roundToInt().coerceAtLeast(0)

    /**
     * Folds one sweat-loss sample into the session total.
     *
     * Verified in the HealthPlatform decompile (BaseSweatLossTracker.runDehydrationAlgorithm):
     * the emitted value is DehydrationLibManager.predict()[1], the library's cumulative total for
     * the running exercise, sent once per exercise stop. So the total is the latest value, never a
     * sum of samples; a lower repeat only happens on error paths, which the caller filters out.
     */
    fun accumulateSweatLoss(accumulatedMl: Int, sample: Int): Int {
        if (sample < 0) return accumulatedMl.coerceAtLeast(0)
        return maxOf(accumulatedMl.coerceAtLeast(0), sample)
    }
}
