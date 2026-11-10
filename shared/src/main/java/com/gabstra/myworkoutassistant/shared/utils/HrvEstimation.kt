package com.gabstra.myworkoutassistant.shared.utils

import kotlin.math.abs
import kotlin.math.sqrt

/**
 * Beat/HR validity from the sensor's own flags (SemHrSensorParam.Flag, verified in the
 * HealthPlatform decompile): NONE(0), FIND_HR(1) and ATTACHED(-1) are usable;
 * DETECT_MOVE(-2), DETACHED(-3), OBJECT(-5), LOW_RELIABILITY(-8) and
 * VERYLOW_RELIABILITY(-10) are not.
 */
object HeartRateQuality {

    private val USABLE_FLAGS = setOf(0, 1, -1)

    fun isUsable(status: Int?): Boolean = status == null || status in USABLE_FLAGS

    fun isUsableBeat(status: Int): Boolean = status in USABLE_FLAGS
}

/**
 * Time-domain heart-rate variability from raw beat-to-beat (IBI) samples.
 *
 * Two filters run before any metric:
 *  - plausible range: 300..2000 ms (30..200 bpm) drops impossible intervals;
 *  - median deviation: intervals further than 25% from the median are treated as artifacts
 *    (a single missed or extra beat otherwise dominates RMSSD).
 *
 * RMSSD needs at least three usable intervals (two differences); SDNN needs at least two.
 * Both return null when there is not enough signal.
 */
object HrvEstimation {

    private const val PLAUSIBLE_IBI_MIN_MS = 300
    private const val PLAUSIBLE_IBI_MAX_MS = 2000
    private const val MAX_MEDIAN_DEVIATION_FRACTION = 0.25

    /**
     * Keeps the beats whose per-interval flag is usable (see [HeartRateQuality]).
     * Beats with no status (older paths) are kept.
     */
    fun filterUsableBeats(ibiMs: List<Int>, statuses: List<Int>): List<Int> {
        if (statuses.isEmpty()) return ibiMs
        return ibiMs.filterIndexed { index, _ ->
            index >= statuses.size || HeartRateQuality.isUsableBeat(statuses[index])
        }
    }

    /**
     * Root mean square of successive differences.
     *
     * @return RMSSD in milliseconds, or null when fewer than three usable intervals remain.
     */
    fun rmssd(ibiMs: List<Int>): Double? {
        val beats = usableBeats(ibiMs)
        if (beats.size < 3) return null

        var squaredDifferenceSum = 0.0
        for (index in 1 until beats.size) {
            val difference = (beats[index] - beats[index - 1]).toDouble()
            squaredDifferenceSum += difference * difference
        }
        return sqrt(squaredDifferenceSum / (beats.size - 1))
    }

    /**
     * Standard deviation of normal-to-normal intervals (sample standard deviation, N-1).
     *
     * @return SDNN in milliseconds, or null when fewer than two usable intervals remain.
     */
    fun sdnn(ibiMs: List<Int>): Double? {
        val beats = usableBeats(ibiMs)
        if (beats.size < 2) return null

        val mean = beats.average()
        var squaredDeviationSum = 0.0
        for (beat in beats) {
            val deviation = beat - mean
            squaredDeviationSum += deviation * deviation
        }
        return sqrt(squaredDeviationSum / (beats.size - 1))
    }

    private fun usableBeats(ibiMs: List<Int>): List<Int> {
        val plausible = ibiMs.filter { it in PLAUSIBLE_IBI_MIN_MS..PLAUSIBLE_IBI_MAX_MS }
        if (plausible.size < 3) return plausible

        val median = median(plausible)
        val limit = median * MAX_MEDIAN_DEVIATION_FRACTION
        return plausible.filter { abs(it - median) <= limit }
    }

    private fun median(values: List<Int>): Double {
        val sorted = values.sorted()
        val middle = sorted.size / 2
        return if (sorted.size % 2 == 1) {
            sorted[middle].toDouble()
        } else {
            (sorted[middle - 1] + sorted[middle]) / 2.0
        }
    }
}
