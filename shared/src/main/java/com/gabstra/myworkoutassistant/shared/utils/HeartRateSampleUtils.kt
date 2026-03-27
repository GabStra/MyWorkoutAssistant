package com.gabstra.myworkoutassistant.shared.utils

fun List<Int>.validHeartRateSamples(): List<Int> = filter { it > 0 }

fun List<Int>.averageValidHeartRateOrNull(): Double? {
    val validSamples = validHeartRateSamples()
    return if (validSamples.isEmpty()) null else validSamples.average()
}
