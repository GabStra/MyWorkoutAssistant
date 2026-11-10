package com.gabstra.myworkoutassistant.reps

import kotlin.math.sqrt

/**
 * Rolling accelerometer stillness gate used by HRV: beat detection is unreliable while the wrist
 * moves, so only quiet windows may contribute beat-to-beat intervals.
 *
 * Pure Kotlin so it can be unit tested; the coordinator feeds it from the capture stream.
 */
class StillnessTracker(
    private val windowNanos: Long = 1_000_000_000L,
    private val stillStdDevThreshold: Float = 0.25f,
    private val minSamples: Int = 5,
) {

    private val samples = ArrayDeque<Pair<Long, Float>>()
    private var still = true

    /** @return true while the last window is quiet. */
    fun addSample(timestampNanos: Long, ax: Float, ay: Float, az: Float): Boolean {
        val magnitude = sqrt(ax * ax + ay * ay + az * az)
        samples.addLast(timestampNanos to magnitude)
        val cutoff = timestampNanos - windowNanos
        while (samples.isNotEmpty() && samples.first().first < cutoff) {
            samples.removeFirst()
        }
        if (samples.size < minSamples) return still

        val mean = samples.sumOf { it.second.toDouble() } / samples.size
        var variance = 0.0
        for ((_, value) in samples) {
            val deviation = value - mean
            variance += deviation * deviation
        }
        still = sqrt(variance / samples.size) < stillStdDevThreshold
        return still
    }

    fun reset() {
        samples.clear()
        still = true
    }
}
