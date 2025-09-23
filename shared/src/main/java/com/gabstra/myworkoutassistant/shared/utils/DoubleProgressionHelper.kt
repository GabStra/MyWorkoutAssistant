package com.gabstra.myworkoutassistant.shared.utils

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
     * - defaultPct: preferred jump when multiple options are within maxPct (e.g., 0.05 = 5%).
     * - maxPct: if the smallest heavier available weight exceeds maxPct, we "ride the weight"
     *   (keep load, add reps) until 'overcapUntil' is reached on all sets.
     * - overcapUntil: how many reps above the range top (per set) allowed before taking the
     *   next available heavier weight even if it’s > maxPct.
     */
    data class LoadJumpPolicy(
        val defaultPct: Double = 0.025,
        val maxPct: Double = 0.5,
        val overcapUntil: Int = 2
    )

    private const val EPS = 1e-9

    private fun anchorToAvailable(current: Double, available: Set<Double>): Double =
        available.filter { it <= current }.maxOrNull() ?: available.minOrNull()!!

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

        // 1) Working anchor = heaviest weight used last time (floored to available)
        val rawAnchor = previousSets.maxOf { it.weight }
        val lastWorkingWeight = anchorToAvailable(rawAnchor, availableWeights)
        val wasNormalized = previousSets.any { kotlin.math.abs(it.weight - lastWorkingWeight) > EPS }

        // 2) Normalize previous reps to the working weight (no stepping: below → bottom)
        val normalizedPrevReps = previousSets.map { s ->
            if (s.weight < lastWorkingWeight - EPS) bottom
            else s.reps.coerceAtLeast(bottom)
        }

        val hitTopEverySet = normalizedPrevReps.all { it >= top }
        val hitOvercapEverySet = normalizedPrevReps.all { it >= top + jumpPolicy.overcapUntil }

        // 3) Decide next working weight (percent band; fallback to overcap)
        var nextWorkingWeight = lastWorkingWeight
        var useOvercap = false

        val heavier = availableWeights.filter { it > lastWorkingWeight }.sorted()
        if (hitTopEverySet && heavier.isNotEmpty()) {
            data class Cand(val w: Double, val pct: Double, val dist: Double)
            val cands = heavier.map { w ->
                val pct = (w - lastWorkingWeight) / lastWorkingWeight
                Cand(w, pct, kotlin.math.abs(pct - jumpPolicy.defaultPct))
            }

            val viable = cands
                .filter { it.pct > 0.0 && it.pct <= jumpPolicy.maxPct + EPS }
                .sortedWith(compareBy<Cand> { it.dist }.thenBy { it.w })

            nextWorkingWeight = when {
                viable.isNotEmpty() -> viable.first().w                   // pick closest to defaultPct within band
                hitOvercapEverySet   -> heavier.first()                   // force next heavier even if > maxPct
                else                 -> { useOvercap = true; lastWorkingWeight } // ride the weight
            }
        } else if (hitTopEverySet) {
            useOvercap = true
        }

        // 4) Decide next reps
        val effectiveTop = if (useOvercap) top + jumpPolicy.overcapUntil else top

        val nextReps: MutableList<Int> =
            if (nextWorkingWeight > lastWorkingWeight) {
                MutableList(setCount) { bottom }                          // on jump → all sets at bottom
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
