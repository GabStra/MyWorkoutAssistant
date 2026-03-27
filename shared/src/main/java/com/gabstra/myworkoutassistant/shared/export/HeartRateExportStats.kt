package com.gabstra.myworkoutassistant.shared.export

import com.gabstra.myworkoutassistant.shared.getEffectiveMaxHeartRate
import com.gabstra.myworkoutassistant.shared.getHeartRateFromPercentage
import com.gabstra.myworkoutassistant.shared.getMaxHearthRatePercentage
import com.gabstra.myworkoutassistant.shared.zoneRanges
import java.time.Duration
import java.time.LocalDateTime
import kotlin.math.sqrt

/**
 * Heart rate zone bounds (BPM) aligned with [WorkoutHistoryScreen] / [zoneRanges].
 */
internal fun heartRateZoneBoundsBpm(
    userAge: Int,
    measuredMaxHeartRate: Int?,
    restingHeartRate: Int?,
): List<IntRange> {
    val zoneStarts = zoneRanges.map { (lowerBoundPercent, _) ->
        getHeartRateFromPercentage(
            lowerBoundPercent,
            userAge,
            measuredMaxHeartRate,
            restingHeartRate,
        )
    }
    val absoluteMax = getHeartRateFromPercentage(
        zoneRanges.last().second,
        userAge,
        measuredMaxHeartRate,
        restingHeartRate,
    )
    return zoneStarts.indices.map { zoneIndex ->
        val lowerBound = zoneStarts[zoneIndex]
        val upperBound = if (zoneIndex < zoneStarts.lastIndex) {
            zoneStarts[zoneIndex + 1] - 1
        } else {
            absoluteMax
        }
        lowerBound..maxOf(lowerBound, upperBound)
    }
}

internal fun zoneIndexForBpm(
    heartRate: Int,
    zoneBounds: List<IntRange>,
): Int {
    val hr = heartRate.toDouble()
    for (zoneIndex in zoneBounds.indices.reversed()) {
        val zoneRange = zoneBounds[zoneIndex]
        if (hr in zoneRange.first.toDouble()..zoneRange.last.toDouble()) {
            return zoneIndex
        }
    }
    return when {
        hr < zoneBounds.first().first -> 0
        hr > zoneBounds.last().last -> zoneBounds.lastIndex
        else -> 0
    }
}

/**
 * Fraction of samples (0..1) per zone index, same length as [zoneBounds].
 */
internal fun standardZoneSampleFractions(
    samplesBpm: List<Int>,
    zoneBounds: List<IntRange>,
): List<Double> {
    if (samplesBpm.isEmpty()) return List(zoneBounds.size) { 0.0 }
    val counts = IntArray(zoneBounds.size)
    for (hr in samplesBpm) {
        if (hr <= 0) continue
        val z = zoneIndexForBpm(hr, zoneBounds).coerceIn(0, zoneBounds.lastIndex)
        counts[z]++
    }
    val total = counts.sum().coerceAtLeast(1)
    return counts.map { it.toDouble() / total.toDouble() }
}

internal fun medianInt(values: List<Int>): Int? {
    if (values.isEmpty()) return null
    val sorted = values.sorted()
    val mid = sorted.size / 2
    return if (sorted.size % 2 == 1) sorted[mid]
    else ((sorted[mid - 1] + sorted[mid]) / 2)
}

/**
 * Population standard deviation of positive integers; null if fewer than 2 values.
 */
internal fun populationStdDevInt(values: List<Int>): Double? {
    if (values.size < 2) return null
    val mean = values.sum().toDouble() / values.size
    val variance = values.sumOf { v ->
        val d = v - mean
        d * d
    } / values.size
    return sqrt(variance)
}

/**
 * Samples from [records] for [intervalStart]..[intervalEnd] relative to [workoutStart],
 * ~1 sample per second, indices clamped to array bounds. Empty if interval invalid.
 */
internal fun sliceHeartRateRecords(
    workoutStart: LocalDateTime,
    records: List<Int>,
    intervalStart: LocalDateTime?,
    intervalEnd: LocalDateTime?,
): List<Int> {
    if (records.isEmpty() || intervalStart == null || intervalEnd == null) return emptyList()
    if (!intervalEnd.isAfter(intervalStart)) return emptyList()
    val offsetSec = Duration.between(workoutStart, intervalStart).seconds.toInt().coerceAtLeast(0)
    val durationSec = Duration.between(intervalStart, intervalEnd).seconds.toInt().coerceAtLeast(0)
    val startIdx = offsetSec.coerceIn(0, records.size)
    val endIdx = (offsetSec + durationSec).coerceIn(0, records.size)
    if (startIdx >= endIdx) return emptyList()
    return records.subList(startIdx, endIdx)
}

internal fun fractionAboveFractionOfMaxHr(
    samplesBpm: List<Int>,
    maxHr: Int,
    thresholdFraction: Double,
): Double? {
    val valid = samplesBpm.filter { it > 0 }
    if (valid.isEmpty()) return null
    val thresholdBpm = maxHr * thresholdFraction
    val count = valid.count { it >= thresholdBpm }
    return count.toDouble() / valid.size.toDouble()
}

internal data class SessionHrDerived(
    val mean: Int,
    val median: Int?,
    val min: Int,
    val max: Int,
    val stdDev: Double?,
    val avgPctOfMaxHr: Float?,
    val peakPctOfMaxHr: Float?,
    val avgHrrPct: Float?,
    val peakHrrPct: Float?,
    val fractionAbove85PctMax: Double?,
    val fractionAbove90PctMax: Double?,
    val validSampleCount: Int,
)

internal fun computeSessionHrDerived(
    validSamples: List<Int>,
    userAge: Int,
    measuredMaxHeartRate: Int?,
    restingHeartRate: Int?,
): SessionHrDerived? {
    if (validSamples.isEmpty()) return null
    val mean = validSamples.average().toInt()
    val median = medianInt(validSamples)
    val min = validSamples.minOrNull() ?: 0
    val max = validSamples.maxOrNull() ?: 0
    val stdDev = populationStdDevInt(validSamples)
    val maxHr = getEffectiveMaxHeartRate(userAge, measuredMaxHeartRate)
    val avgPctOfMaxHr = if (maxHr > 0) (mean.toFloat() / maxHr.toFloat()) * 100f else null
    val peakPctOfMaxHr = if (maxHr > 0) (max.toFloat() / maxHr.toFloat()) * 100f else null
    val avgHrrPct = if (restingHeartRate != null) {
        getMaxHearthRatePercentage(mean, userAge, measuredMaxHeartRate, restingHeartRate)
    } else null
    val peakHrrPct = if (restingHeartRate != null) {
        getMaxHearthRatePercentage(max, userAge, measuredMaxHeartRate, restingHeartRate)
    } else null
    val f85 = fractionAboveFractionOfMaxHr(validSamples, maxHr, 0.85)
    val f90 = fractionAboveFractionOfMaxHr(validSamples, maxHr, 0.90)
    val n = validSamples.size
    return SessionHrDerived(
        mean = mean,
        median = median,
        min = min,
        max = max,
        stdDev = stdDev,
        avgPctOfMaxHr = avgPctOfMaxHr,
        peakPctOfMaxHr = peakPctOfMaxHr,
        avgHrrPct = avgHrrPct,
        peakHrrPct = peakHrrPct,
        fractionAbove85PctMax = f85,
        fractionAbove90PctMax = f90,
        validSampleCount = n,
    )
}
