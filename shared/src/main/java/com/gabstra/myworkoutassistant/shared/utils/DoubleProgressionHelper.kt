package com.gabstra.myworkoutassistant.shared.utils

import kotlin.math.ceil
import kotlin.math.floor

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
        val defaultPct: Double = 0.05,  // ~4% default when unsure (within the 3–10% guidance)
        val minPct: Double = 0.02,      // ~2%
        val maxPct: Double = 0.1,      // ~10%
        val overcapUntil: Int = 2       // allow +1 rep over top across sets before oversized jump
    )

    /**
     * Curve-free double progression with normalization, configurable rep increment strategy,
     * and percent-based load jumps with an overcap fallback.
     *
     * Adds (optional) tonnage check on consolidation to avoid >~10% volume drop.
     */
    fun planNextSession(
        previousSets: List<SimpleSet>,
        availableWeights: Set<Double>,
        repsRange: IntRange,
        strategy: IncrementStrategy = IncrementStrategy.LOWEST_FIRST,
        jumpPolicy: LoadJumpPolicy = LoadJumpPolicy(),
        enableTonnageCheck: Boolean = true,
        maxDropPct: Double = 0.20
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

        // 3) Decide next working weight (percent-based band, else overcap fallback)
        val hitTopEverySet = normalizedPrevReps.all { it >= top }

        var nextWorkingWeight = lastWorkingWeight
        var useOvercap = false
        var predictedRepsOnJump: Int? = null

        if (hitTopEverySet) {
            val heavier = availableWeights.filter { it > lastWorkingWeight }.sorted()
            // Score candidates by: (1) predicted reps >= bottom, (2) closeness to defaultPct
            data class Cand(val w: Double, val pct: Double, val repsPred: Double, val dist: Double)

            val cands = heavier.map { w ->
                val pct = (w - lastWorkingWeight) / lastWorkingWeight
                val repsPred = top - (pct / 0.0333)            // ~1 rep per 3.33%
                val dist = kotlin.math.abs(pct - jumpPolicy.defaultPct)
                Cand(w, pct, repsPred, dist)
            }

            val viable = cands
                .filter { it.pct in jumpPolicy.minPct - 1e-12 .. jumpPolicy.maxPct + 1e-12 }
                .filter { it.repsPred >= bottom - 1e-9 }
                .sortedWith(compareBy<Cand> { it.dist }.thenBy { it.w })

            if (viable.isNotEmpty()) {
                val best = viable.first()
                nextWorkingWeight = best.w
                // Round prediction to an executable target (floor tends to be safer than round here)
                predictedRepsOnJump = best.repsPred.toInt().coerceIn(bottom, top)
            } else {
                useOvercap = true
            }
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

        // --- Tonnage check (optional) on consolidation only ---
        val previousVolume = previousSets.sumOf { it.weight * it.reps }
        var nextSets = List(setCount) { i -> SimpleSet(nextWorkingWeight, nextReps[i]) }
        var newVolume = nextSets.sumOf { it.weight * it.reps }

        if (enableTonnageCheck && nextWorkingWeight == lastWorkingWeight && wasNormalized) {
            val minAllowed = previousVolume * (1.0 - maxDropPct)

            if (newVolume + 1e-9 < minAllowed) {
                val baselineMaxSetTonnage = previousSets.maxOf { it.weight * it.reps }
                var needed = ceil((minAllowed - newVolume) / nextWorkingWeight).toInt().coerceAtLeast(0)

                // Per-set rep ceiling from baseline max tonnage + normal caps
                val capByBaseline = floor(baselineMaxSetTonnage / nextWorkingWeight).toInt()
                val perSetCap = minOf(effectiveTop, capByBaseline)

                // Valid sets = those below perSetCap; compute total headroom
                val validIdx = (0 until setCount).filter { nextReps[it] < perSetCap }
                val totalHeadroom = validIdx.sumOf { (perSetCap - nextReps[it]).coerceAtLeast(0) }

                // Can't exceed headroom or we’d raise baseline max set tonnage
                needed = minOf(needed, totalHeadroom)

                // Round-robin distribution across valid sets (stable, even spread)
                var i = 0
                var progressed: Boolean
                while (needed > 0 && validIdx.isNotEmpty()) {
                    progressed = false
                    for (k in validIdx.indices) {
                        if (needed == 0) break
                        val idx = validIdx[(i + k) % validIdx.size]
                        val headroom = (perSetCap - nextReps[idx]).coerceAtLeast(0)
                        if (headroom > 0) {
                            nextReps[idx] += 1
                            needed -= 1
                            progressed = true
                        }
                    }
                    if (!progressed) break // no more headroom anywhere
                    i = (i + 1) % (validIdx.size.coerceAtLeast(1))
                }

                nextSets = List(setCount) { j -> SimpleSet(nextWorkingWeight, nextReps[j]) }
                newVolume = nextSets.sumOf { it.weight * it.reps }
            }
        }
        // ------------------------------------------------------

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
