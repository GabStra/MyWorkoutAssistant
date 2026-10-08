package com.gabstra.myworkoutassistant.shared.utils

import com.gabstra.myworkoutassistant.shared.running.RunningResult
import kotlin.math.roundToInt

private const val VO2MAX_PLAUSIBLE_LOW = 15.0
private const val VO2MAX_PLAUSIBLE_HIGH = 90.0

/**
 * Resting-HR estimate (Uth-Søvoldius): VO2max ≈ 15.3 × HRmax / HRrest.
 *
 * Zero-effort baseline that works with whatever the profile already has (HRmax
 * measured or age-predicted, HRrest user-set or Health-Connect-derived). Population
 * accuracy is limited (~±20-25%); anything better (Health Connect record, run-based)
 * outranks it.
 */
fun estimateVo2MaxFromRestingHr(maxHeartRateBpm: Int, restingHeartRateBpm: Int): Double? {
    if (maxHeartRateBpm !in 100..250 || restingHeartRateBpm !in 30..120) return null
    val value = 15.3 * (maxHeartRateBpm.toDouble() / restingHeartRateBpm)
    return value.coerceIn(VO2MAX_PLAUSIBLE_LOW, VO2MAX_PLAUSIBLE_HIGH)
        .let { (it * 10).roundToInt() / 10.0 }
}

/**
 * Submaximal run-based estimate: VO2 from the ACSM level-running equation at the
 * average speed, scaled by HRmax/HRavg.
 *
 * Only trusts steady submaximal efforts: >= 1 km, >= 4 min, >= 1.6 m/s (running
 * equation invalid below that), average HR within 60-90% of HRmax (below that the
 * HR-VO2 coupling is noisy, above it the ratio underestimates). Returns null when
 * the run does not qualify.
 */
fun estimateVo2MaxFromRun(result: RunningResult, maxHeartRateBpm: Int): Double? {
    val distanceMeters = result.distanceMeters ?: return null
    val durationMillis = result.elapsedTimeMillis
    val averageHr = result.averageHeartRateBpm ?: return null
    if (maxHeartRateBpm !in 100..250) return null
    if (distanceMeters < 1_000.0) return null
    if (durationMillis < 4 * 60_000L) return null
    val seconds = durationMillis / 1000.0
    if (seconds <= 0.0) return null
    val speedMps = distanceMeters / seconds
    if (speedMps < 1.6) return null
    val hrFraction = averageHr.toDouble() / maxHeartRateBpm
    if (hrFraction < 0.60 || hrFraction > 0.90) return null

    // ACSM level running: VO2 (mL/kg/min) = 0.2 * speed(m/min) + 3.5
    val submaxVo2 = 0.2 * (speedMps * 60.0) + 3.5
    val vo2Max = submaxVo2 / hrFraction
    return vo2Max.coerceIn(VO2MAX_PLAUSIBLE_LOW, VO2MAX_PLAUSIBLE_HIGH)
        .let { (it * 10).roundToInt() / 10.0 }
}
