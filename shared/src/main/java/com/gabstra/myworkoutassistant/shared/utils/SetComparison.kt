package com.gabstra.myworkoutassistant.shared.utils

import com.gabstra.myworkoutassistant.shared.round

enum class Ternary { BELOW, EQUAL, ABOVE, MIXED }

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

