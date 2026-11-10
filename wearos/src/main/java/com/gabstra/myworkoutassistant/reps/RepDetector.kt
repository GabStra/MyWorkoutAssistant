package com.gabstra.myworkoutassistant.reps

import kotlin.math.exp
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

/**
 * Rep counter driven by the magnitude of raw acceleration samples.
 *
 * The signal path is: |a| -> minus a slow gravity baseline -> 3-sample moving average.
 * A rep is one concentric peak above +threshold followed by an eccentric valley below
 * -threshold. Thresholds adapt to the last counted peak so soft and hard sets both register.
 *
 * Pure Kotlin only: no Android dependencies.
 */
class RepDetector(
    /** False when the input is LINEAR_ACCELERATION (gravity already removed by the platform). */
    private val subtractGravity: Boolean = true,
) {

    var reps: Int = 0
        private set

    private var gravityBaseline = Float.NaN
    private var lastTimestampNs = 0L

    /** Decaying magnitude of the last counted concentric peak; drives the adaptive threshold. */
    private var recentPeak = 0f

    private val smoothWindow = FloatArray(3)
    private var smoothIndex = 0
    private var smoothCount = 0

    private var peakTimestampNs = NO_TIMESTAMP
    private var peakMagnitude = 0f
    private var lastRepTimestampNs = NO_TIMESTAMP

    fun addSample(timestampNs: Long, ax: Float, ay: Float, az: Float) {
        val magnitude = sqrt(ax * ax + ay * ay + az * az)

        val dt = (timestampNs - lastTimestampNs).coerceAtLeast(0L) / 1e9f
        lastTimestampNs = timestampNs
        if (subtractGravity) {
            if (gravityBaseline.isNaN()) {
                gravityBaseline = magnitude
            } else if (dt > 0f) {
                gravityBaseline += (1f - exp(-dt / BASELINE_TAU_S)) * (magnitude - gravityBaseline)
            }
        }
        if (dt > 0f) {
            recentPeak -= recentPeak * min(1f, dt / PEAK_DECAY_S)
        }

        val linear = if (subtractGravity) magnitude - gravityBaseline else magnitude
        smoothWindow[smoothIndex] = linear
        smoothIndex = (smoothIndex + 1) % smoothWindow.size
        if (smoothCount < smoothWindow.size) smoothCount++
        var sum = 0f
        for (i in 0 until smoothCount) sum += smoothWindow[i]
        val smoothed = sum / smoothCount

        val threshold = max(MIN_THRESHOLD, ADAPTIVE_FACTOR * recentPeak)

        if (peakTimestampNs == NO_TIMESTAMP) {
            if (smoothed > threshold) {
                peakTimestampNs = timestampNs
                peakMagnitude = smoothed
            }
            return
        }

        if (smoothed > peakMagnitude) peakMagnitude = smoothed
        val pairDurationNs = timestampNs - peakTimestampNs

        when {
            smoothed < -threshold -> {
                // Refractory is measured between rep completions (valleys), not from peak to
                // valley: a 3 Hz cycle lands its valley only ~167 ms after its peak.
                if (pairDurationNs <= MAX_PEAK_TO_VALLEY_NS &&
                    (lastRepTimestampNs == NO_TIMESTAMP ||
                        timestampNs - lastRepTimestampNs >= REFRACTORY_NS)
                ) {
                    reps++
                    lastRepTimestampNs = timestampNs
                    recentPeak = max(recentPeak, peakMagnitude)
                }
                peakTimestampNs = NO_TIMESTAMP
            }

            pairDurationNs > MAX_PEAK_TO_VALLEY_NS -> peakTimestampNs = NO_TIMESTAMP
        }
    }

    fun reset() {
        reps = 0
        gravityBaseline = Float.NaN
        lastTimestampNs = 0L
        recentPeak = 0f
        smoothIndex = 0
        smoothCount = 0
        peakTimestampNs = NO_TIMESTAMP
        peakMagnitude = 0f
        lastRepTimestampNs = NO_TIMESTAMP
    }

    private companion object {
        const val NO_TIMESTAMP = Long.MIN_VALUE

        /** Time constant of the gravity estimate (the "~2 s running baseline"). */
        const val BASELINE_TAU_S = 2f

        /** Floor threshold in m/s²; the adaptive term can only raise it. */
        const val MIN_THRESHOLD = 1.5f
        const val ADAPTIVE_FACTOR = 0.4f

        /** Lets the adaptive threshold fall back after a hard set. */
        const val PEAK_DECAY_S = 10f

        const val MAX_PEAK_TO_VALLEY_NS = 2_500_000_000L
        const val REFRACTORY_NS = 300_000_000L
    }
}
