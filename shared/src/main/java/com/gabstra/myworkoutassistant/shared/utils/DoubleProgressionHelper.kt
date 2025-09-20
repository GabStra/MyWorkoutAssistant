package com.gabstra.myworkoutassistant.shared.utils

import kotlin.math.abs

object DoubleProgressionHelper {
    data class Plan(
        val sets: List<SimpleSet>,     // next-session targets (one working weight across sets)
        val newVolume: Double,         // kg·reps next session
        val previousVolume: Double,    // kg·reps last session
    )

    enum class IncrementStrategy { ALL_SETS, LOWEST_FIRST, ONE_REP_TOTAL }

    /**
     * Policy for deciding load jumps when all sets reach the top of the rep range.
     *
     * - defaultPct: target jump when options allow (e.g., 0.05 = 5%).
     * - minPct/maxPct: acceptable band; if the smallest heavier available weight exceeds maxPct,
     *   we "ride the weight" (keep load, add reps) until 'overcapUntil' is reached on all sets.
     * - overcapUntil: how many reps above the range top (per set) you’ll allow before taking the
     *   next available heavier weight even if it’s > maxPct.
     */
    data class LoadJumpPolicy(
        val defaultPct: Double = 0.05,  // ~5% default when unsure (within the 3–10% guidance)
        val maxPct: Double = 0.1,      // ~10%
        val overcapUntil: Int = 2       // allow +2 rep over top across sets before oversized jump
    )

    private const val EPLEY_K = 30.0 // 1RM ≈ w * (1 + r/30)
    private const val EPS = 1e-9

    private fun predictRepsAtWeight(weight: Double, set: SimpleSet): Int {
        require(weight > 0 && set.weight > 0)
        val est1RM = set.weight * (1.0 + set.reps / EPLEY_K)
        val raw = EPLEY_K * (est1RM / weight - 1.0)
        return raw.toInt()
    }

    private fun anchorToAvailable(current: Double, available: Set<Double>): Double =
        available.filter { it <= current }.maxOrNull() ?: available.minOrNull()!!

    /**
     * Curve-free double progression with normalization, configurable rep increment strategy,
     * and percent-based load jumps with an overcap fallback.
     */
    fun planNextSession(
        previousSets: List<SimpleSet>,
        availableWeights: Set<Double>,
        repsRange: IntRange,
        strategy: IncrementStrategy = IncrementStrategy.LOWEST_FIRST,
        jumpPolicy: LoadJumpPolicy = LoadJumpPolicy()
    ): Plan {
        require(previousSets.isNotEmpty()) { "previousSets cannot be empty" }
        require(availableWeights.isNotEmpty()) { "availableWeights cannot be empty" }
        require(repsRange.first > 0 && repsRange.last >= repsRange.first) { "Invalid repsRange" }
        require(previousSets.all { it.weight > 0 && it.reps >= 0 })

        val setCount = previousSets.size
        val bottom = repsRange.first
        val top = repsRange.last

        // 1) Working anchor = heaviest weight used last time
        val rawAnchor = previousSets.maxOf { it.weight }
        val lastWorkingWeight = anchorToAvailable(rawAnchor, availableWeights)
        val wasNormalized = previousSets.any { abs(it.weight - lastWorkingWeight) > EPS }

        // 2) Normalize previous reps to the working weight (Epley-based)
        val normalizedPrevReps = previousSets.map { s ->
            if (s.weight < lastWorkingWeight - EPS) {
                // project up to working weight; don't top-clamp here
                predictRepsAtWeight(
                    weight = lastWorkingWeight,
                    set = s
                ).coerceIn(repsRange)
            } else {
                // keep the actual reps (just bottom-clamp)
                s.reps
            }
        }

        // 3) Decide next working weight (percent-based band, else overcap fallback)
        val hitTopEverySet = normalizedPrevReps.all { it >= top }

        var nextWorkingWeight = lastWorkingWeight
        var useOvercap = false
        var predictedRepsOnJump: Int? = null

        val heavier = availableWeights.filter { it > lastWorkingWeight }.sorted()
        if (hitTopEverySet && heavier.isNotEmpty()) {
            // Score candidates by: (1) predicted reps >= bottom, (2) closeness to defaultPct
            data class Cand(val w: Double, val pct: Double, val repsPred: Int, val dist: Double)
            val worstAtAnchor = normalizedPrevReps.minOrNull()!!
            val cands = heavier.map { w ->
                val pct = (w - lastWorkingWeight) / lastWorkingWeight
                val repsPred = predictRepsAtWeight(w, SimpleSet(lastWorkingWeight, worstAtAnchor))
                Cand(w, pct, repsPred, abs(pct - jumpPolicy.defaultPct))
            }

            val viable = cands
                .filter { it.pct > 0.0 && it.pct <= jumpPolicy.maxPct + EPS }
                .filter { it.repsPred >= bottom }
                .sortedWith(compareBy<Cand> { it.dist }.thenBy { it.w })

            if (viable.isNotEmpty()) {
                val best = viable.first()
                nextWorkingWeight = best.w
                // Round prediction to an executable target (floor tends to be safer than round here)
                predictedRepsOnJump = best.repsPred.coerceIn(bottom, top)
            } else {
                useOvercap = true
            }
        } else if (hitTopEverySet) {
            useOvercap = true
        }

        // 4) Decide next reps (+overcap if we couldn't jump)
        val effectiveTop = if (useOvercap) top + jumpPolicy.overcapUntil else top

        val nextReps: MutableList<Int> =
            if (nextWorkingWeight > lastWorkingWeight) {
                val repsTarget = predictedRepsOnJump ?: bottom
                MutableList(setCount) { repsTarget }
            } else if (wasNormalized) {
                normalizedPrevReps.toMutableList()
            } else {
                nextRepsSameWeight(normalizedPrevReps, effectiveTop, strategy).toMutableList()
            }

        val previousVolume = previousSets.sumOf { it.weight * it.reps }
        val nextSets = List(setCount) { i -> SimpleSet(nextWorkingWeight, nextReps[i]) }
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
        topOrOvercap: Int,
        strategy: IncrementStrategy
    ): List<Int> = when (strategy) {
        IncrementStrategy.ALL_SETS ->
            prev.map { (it + 1).coerceAtMost(topOrOvercap) }

        IncrementStrategy.LOWEST_FIRST -> {
            val res = prev.toMutableList()
            val lowestIdx = res.indices.minByOrNull { res[it] } ?: return res
            if (res[lowestIdx] < topOrOvercap) res[lowestIdx] = res[lowestIdx] + 1
            res
        }

        IncrementStrategy.ONE_REP_TOTAL -> {
            val res = prev.toMutableList()
            for (i in res.indices) {
                if (res[i] < topOrOvercap) { res[i] = res[i] + 1; break }
            }
            res
        }
    }

    data class DeloadOptions(
        val weightFactor: Double = 0.9,   // % of last working weight (e.g., 0.9 = 90%)
        val repsDrop: Int = 2,            // subtract this many reps from each set
        val cutSetsTo: Int? = null        // optionally reduce number of sets (e.g., 2)
    )

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

    private fun floorToAvailable(target: Double, available: Set<Double>): Double {
        val underOrEq = available.filter { it <= target }
        return when {
            underOrEq.isNotEmpty() -> underOrEq.maxOrNull()!!
            else -> available.minOrNull()!!
        }
    }
}
