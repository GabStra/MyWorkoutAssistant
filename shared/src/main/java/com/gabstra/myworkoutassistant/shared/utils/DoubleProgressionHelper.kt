package com.gabstra.myworkoutassistant.shared.utils

object DoubleProgressionHelper {
    data class Plan(
        val sets: List<SimpleSet>,     // next-session targets (one working weight across sets)
        val newVolume: Double,         // kg·reps next session
        val previousVolume: Double,    // kg·reps last session
    )

    enum class IncrementStrategy { ALL_SETS, LOWEST_FIRST, ONE_REP_TOTAL }

    /**
     * Curve-free double progression with normalization and configurable rep increment strategy.
     *
     * Rules:
     * 1) Working anchor = heaviest weight used last time.
     * 2) Normalize: sets done lighter reset to bottom-of-range reps; sets at working weight keep their reps (capped).
     * 3) If ALL normalized sets are at top-of-range → jump to next strictly heavier available weight; else keep weight.
     * 4) If weight jumped → all sets = bottom-of-range; else add reps using the chosen strategy (capped at top).
     */
    fun planNextSession(
        previousSets: List<SimpleSet>,
        availableWeights: Set<Double>,
        repsRange: IntRange,
        strategy: IncrementStrategy = IncrementStrategy.LOWEST_FIRST
    ): Plan {
        require(previousSets.isNotEmpty()) { "previousSets cannot be empty" }
        require(availableWeights.isNotEmpty()) { "availableWeights cannot be empty" }
        require(repsRange.first > 0 && repsRange.last >= repsRange.first) { "Invalid repsRange" }

        val setCount = previousSets.size
        val bottom = repsRange.first
        val top = repsRange.last
        val eps = 1e-9

        // 1) Working anchor = heaviest weight used last time
        val lastWorkingWeight = previousSets.maxOf { it.weight }

        val wasNormalized = previousSets.any { it.weight < lastWorkingWeight - eps }

        // 2) Normalize previous reps to the working weight
        val normalizedPrevReps: List<Int> = previousSets.map { s ->
            if (s.weight >= lastWorkingWeight - eps) s.reps.coerceAtMost(top) else bottom
        }

        // 3) Decide next working weight (strictly higher if all sets at top)
        val hitTopEverySet = normalizedPrevReps.all { it >= top }
        val nextWorkingWeight =
            if (hitTopEverySet) {
                availableWeights.filter { it > lastWorkingWeight }.minOrNull() ?: lastWorkingWeight
            } else lastWorkingWeight

        // 4) Decide next reps
        val nextReps: List<Int> =
            if (nextWorkingWeight > lastWorkingWeight) {
                List(setCount) { bottom }
            } else if (wasNormalized) {
                // consolidate at one weight first: no rep increases this session
                normalizedPrevReps
            } else {
                // normal progression at same weight
                nextRepsSameWeight(normalizedPrevReps, top, strategy)
            }

        // Build next sets (single working weight across all sets)
        val nextSets = List(setCount) { i -> SimpleSet(nextWorkingWeight, nextReps[i]) }

        // Volumes
        val previousVolume = previousSets.sumOf { it.weight * it.reps }
        val newVolume = nextSets.sumOf { it.weight * it.reps }

        return Plan(
            sets = nextSets.sortedByDescending { it.weight * it.reps },
            newVolume = newVolume,
            previousVolume = previousVolume
        )
    }

    // ---- helpers ----

    private fun nextRepsSameWeight(
        prev: List<Int>,
        top: Int,
        strategy: IncrementStrategy
    ): List<Int> = when (strategy) {
        IncrementStrategy.ALL_SETS ->
            prev.map { (it + 1).coerceAtMost(top) }

        IncrementStrategy.LOWEST_FIRST -> {
            val res = prev.toMutableList()
            // increment exactly one of the lowest-rep sets (small fatigue jump)
            val lowestIdx = res.indices.minByOrNull { res[it] } ?: return res
            if (res[lowestIdx] < top) res[lowestIdx] = res[lowestIdx] + 1
            res
        }

        IncrementStrategy.ONE_REP_TOTAL -> {
            val res = prev.toMutableList()
            // add a single rep to the first set that isn't capped
            for (i in res.indices) {
                if (res[i] < top) { res[i] = res[i] + 1; break }
            }
            res
        }
    }

    data class DeloadOptions(
        val weightFactor: Double = 0.9,   // % of last working weight (e.g., 0.9 = 90%)
        val repsDrop: Int = 2,            // subtract this many reps from each set
        val cutSetsTo: Int? = null       // optionally reduce number of sets (e.g., 2)
    )

    /**
     * Produce a deload session:
     * - Reduce working weight by weightFactor (floored to the heaviest available <= target).
     * - Reduce reps by repsDrop (not below bottom of range).
     * - Optionally cut number of sets.
     * - If no lighter available weight exists, tries a second, lower factor; if still none, keeps weight and only reduces reps/sets.
     */
    fun planDeloadSession(
        previousSets: List<SimpleSet>,
        availableWeights: Set<Double>,
        repsRange: IntRange,
        options: DeloadOptions = DeloadOptions()
    ): Plan {
        require(previousSets.isNotEmpty()) { "previousSets cannot be empty" }
        require(availableWeights.isNotEmpty()) { "availableWeights cannot be empty" }
        require(repsRange.first > 0 && repsRange.last >= repsRange.first) { "Invalid repsRange" }

        val bottom = repsRange.first
        val top = repsRange.last
        val lastWorkingWeight = previousSets.maxOf { it.weight }

        // Target lighter working weight
        val target1 = lastWorkingWeight * options.weightFactor
        val w1 = floorToAvailable(target1, availableWeights)
        val nextWorkingWeight = if (w1 < lastWorkingWeight) w1 else lastWorkingWeight

        // Decide set count (optionally cut)
        val setCount = options.cutSetsTo?.coerceAtLeast(1)?.coerceAtMost(previousSets.size) ?: previousSets.size

        // New reps: reduce by repsDrop, clamp to [bottom, top], and never increase relative to previous
        val basePrevReps = previousSets
            .sortedByDescending { it.weight } // prioritize keeping the heavier sets if cutting
            .take(setCount)
            .map { it.reps.coerceIn(bottom, top) }

        val nextReps = basePrevReps.map { prev -> maxOf(bottom, prev - options.repsDrop) }

        // Build sets: single working weight across all sets
        val nextSets = List(setCount) { i -> SimpleSet(nextWorkingWeight, nextReps[i]) }

        val previousVolume = previousSets.sumOf { it.weight * it.reps }
        val newVolume = nextSets.sumOf { it.weight * it.reps }

        return Plan(
            sets = nextSets.sortedByDescending { it.weight * it.reps },
            newVolume = newVolume,
            previousVolume = previousVolume
        )
    }

    // --- internal ---

    private fun floorToAvailable(target: Double, available: Set<Double>): Double {
        // heaviest available <= target, or the lightest available if none
        val underOrEq = available.filter { it <= target }
        return when {
            underOrEq.isNotEmpty() -> underOrEq.maxOrNull()!!
            else -> available.minOrNull()!!
        }
    }
}
