package com.gabstra.myworkoutassistant.shared.utils

import com.gabstra.myworkoutassistant.shared.round

enum class Ternary { BELOW, EQUAL, ABOVE, MIXED }

data class ProgressionLifecycleComparisonConfig(
    val repsRange: IntRange,
    val availableWeights: kotlin.collections.Set<Double>,
    val jumpPolicy: DoubleProgressionHelper.LoadJumpPolicy = DoubleProgressionHelper.LoadJumpPolicy(),
    val incrementStrategy: DoubleProgressionHelper.IncrementStrategy = DoubleProgressionHelper.IncrementStrategy.LOWEST_FIRST,
)

private val simpleSetComparator =
    compareBy<SimpleSet>({ it.weight.round(2) }, { it.reps })

private fun normalizeSets(list: List<SimpleSet>): List<SimpleSet> =
    list.sortedWith(simpleSetComparator)

// ---- 2) Order-insensitive equality (for "same as original") ----
fun listsEqualUnordered(a: List<SimpleSet>, b: List<SimpleSet>): Boolean =
    a.size == b.size && normalizeSets(a) == normalizeSets(b)

// ---- 3) Order-insensitive ternary compare (for vs expected / vs last) ----
private fun compareSets(a: SimpleSet, b: SimpleSet): Int = when {
    a.weight.round(2) > b.weight.round(2) ||
            (a.weight.round(2) == b.weight.round(2) && a.reps > b.reps) -> 1
    a.weight.round(2) == b.weight.round(2) && a.reps == b.reps -> 0
    else -> -1
}

fun compareSetListsUnordered(a: List<SimpleSet>, b: List<SimpleSet>): Ternary {
    if (a.size != b.size) return Ternary.MIXED
    val A = normalizeSets(a)
    val B = normalizeSets(b)

    var pos = 0
    var neg = 0
    for (i in A.indices) {
        when (compareSets(A[i], B[i])) {
            1  -> pos++
            -1 -> neg++
            // 0 (equal) is ignored
        }
    }

    return when {
        pos > 0 && neg == 0 -> Ternary.ABOVE   // some improved, rest equal
        neg > 0 && pos == 0 -> Ternary.BELOW   // some worse, rest equal
        pos == 0 && neg == 0 -> Ternary.EQUAL  // all equal
        else -> Ternary.MIXED                  // both improved and worse present
    }
}

fun compareSetListsForProgressionLifecycle(
    current: List<SimpleSet>,
    baseline: List<SimpleSet>,
    config: ProgressionLifecycleComparisonConfig,
): Ternary {
    val plannedNextSets = runCatching {
        DoubleProgressionHelper.planNextSession(
            previousSets = baseline,
            availableWeights = config.availableWeights,
            repsRange = config.repsRange,
            strategy = config.incrementStrategy,
            jumpPolicy = config.jumpPolicy,
        ).sets
    }.getOrNull()

    return compareSetListsForProgressionLifecycle(
        current = current,
        baseline = baseline,
        plannedNextSets = plannedNextSets,
    )
}

fun compareSetListsForProgressionLifecycle(
    current: List<SimpleSet>,
    baseline: List<SimpleSet>,
    plannedNextSets: List<SimpleSet>?,
): Ternary {
    if (current.size != baseline.size) return Ternary.MIXED
    if (plannedNextSets != null && plannedNextSets.size != baseline.size) return compareSetListsUnordered(current, baseline)

    val currentSets = normalizeSets(current)
    val baselineSets = normalizeSets(baseline)
    val plannedSets = plannedNextSets?.let(::normalizeSets)

    var pos = 0
    var neg = 0
    for (i in currentSets.indices) {
        when (compareSetForProgressionLifecycle(currentSets[i], baselineSets[i], plannedSets?.get(i))) {
            1 -> pos++
            -1 -> neg++
        }
    }

    return when {
        pos > 0 && neg == 0 -> Ternary.ABOVE
        neg > 0 && pos == 0 -> Ternary.BELOW
        pos == 0 && neg == 0 -> Ternary.EQUAL
        else -> Ternary.MIXED
    }
}

private fun compareSetForProgressionLifecycle(
    current: SimpleSet,
    baseline: SimpleSet,
    plannedNext: SimpleSet?,
): Int {
    if (compareSets(current, baseline) == 0) return 0

    val isHigherLoadLowerReps =
        current.weight.round(2) > baseline.weight.round(2) && current.reps < baseline.reps
    if (isHigherLoadLowerReps) {
        return if (
            plannedNext != null &&
            isLoadJumpWithRepReset(baseline, plannedNext) &&
            current.weight.round(2) >= plannedNext.weight.round(2) &&
            current.reps >= plannedNext.reps
        ) {
            1
        } else {
            -1
        }
    }

    if (plannedNext != null && isLoadJumpWithRepReset(baseline, plannedNext)) {
        return when {
            compareSets(current, plannedNext) >= 0 -> 1
            current.weight.round(2) == baseline.weight.round(2) && current.reps > baseline.reps -> 1
            current.reps == baseline.reps && current.weight.round(2) > baseline.weight.round(2) -> 1
            compareSets(current, plannedNext) < 0 -> -1
            else -> compareSets(current, baseline)
        }
    }

    return compareSets(current, baseline)
}

private fun isLoadJumpWithRepReset(baseline: SimpleSet, plannedNext: SimpleSet): Boolean {
    return plannedNext.weight.round(2) > baseline.weight.round(2) && plannedNext.reps < baseline.reps
}

