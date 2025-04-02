package com.gabstra.myworkoutassistant.shared.utils

import kotlin.math.pow

class HeartRateRegression(
    private val maxDataPoints: Int = 10,
    private val maxAgeSeconds: Double? = 10.0
) {
    private val timePoints = mutableListOf<Double>() // Time in seconds relative to start
    private val heartRates = mutableListOf<Int>() // BPM measurements
    private var startTime: Long? = null // Use Long for System.currentTimeMillis consistency

    private fun ensureStartTime() {
        if (startTime == null) {
            startTime = System.currentTimeMillis()
        }
    }

    fun addReading(bpm: Int): RegressionResult? {
        ensureStartTime()
        // Use milliseconds internally for time diff, convert to seconds for list
        val currentMillis = System.currentTimeMillis()
        val currentTimeSeconds = (currentMillis - startTime!!) / 1000.0

        timePoints.add(currentTimeSeconds)
        heartRates.add(bpm)

        // --- Drop old points ---
        // 1. Drop points older than maxAgeSeconds (if enabled)
        if (maxAgeSeconds != null && maxAgeSeconds > 0 && maxAgeSeconds != Double.MAX_VALUE) {
            val minTimeSeconds = currentTimeSeconds - maxAgeSeconds
            // Remove efficiently from the beginning while the oldest is too old
            while (timePoints.isNotEmpty() && timePoints.first() < minTimeSeconds) {
                timePoints.removeAt(0)
                heartRates.removeAt(0)
            }
        }

        // 2. Drop points exceeding maxDataPoints count (oldest first)
        while (timePoints.size > maxDataPoints) {
            timePoints.removeAt(0)
            heartRates.removeAt(0)
        }
        // ----------------------

        return performRegression()
    }

    /**
     * Performs linear regression on the collected data.
     *
     * @return The regression results including slope, intercept, and R-squared
     */
    fun performRegression(): RegressionResult {
        val n = timePoints.size
        if (n < 2) {
            // Should not happen if called after addReading check, but safeguard
            return RegressionResult(0.0, heartRates.firstOrNull()?.toDouble() ?: 0.0, 0.0, "stable")
        }

        // Calculate means
        val meanX = timePoints.sum() / n
        val meanY = heartRates.sum().toDouble() / n

        // Calculate slope (m) and y-intercept (b)
        var numerator = 0.0
        var denominator = 0.0

        for (i in 0 until n) {
            numerator += (timePoints[i] - meanX) * (heartRates[i] - meanY)
            denominator += (timePoints[i] - meanX).pow(2)
        }

        val slope = if (denominator > 1e-9) numerator / denominator else 0.0 // Slope is BPM / second
        val intercept = meanY - slope * meanX

        // Calculate R-squared (coefficient of determination)
        val predictions = timePoints.map { x -> slope * x + intercept }

        val totalSumSquares = heartRates.sumOf { y ->
            (y - meanY).pow(2)
        }

        // Avoid division by zero if all Y values are the same
        if (totalSumSquares < 1e-9) {
            return RegressionResult(
                slope = slope,
                intercept = intercept,
                rSquared = 1.0, // Perfect fit if all points are the same
                trend = when {
                    slope > 0.0001 -> "increasing" // Add small tolerance for floating point
                    slope < -0.0001 -> "decreasing"
                    else -> "stable"
                }
            )
        }

        val residualSumSquares = heartRates.mapIndexed { i, y ->
            (y - predictions[i]).pow(2)
        }.sum()

        // Ensure rSquared is not negative due to floating point errors, and handle NaN
        val calculatedRSquared = 1.0 - (residualSumSquares / totalSumSquares)
        val rSquared = if (calculatedRSquared.isNaN() || calculatedRSquared < 0) 0.0 else if (calculatedRSquared > 1.0) 1.0 else calculatedRSquared


        return RegressionResult(
            slope = slope,
            intercept = intercept,
            rSquared = rSquared,
            trend = when {
                slope > 0.0001 -> "increasing" // Add small tolerance
                slope < -0.0001 -> "decreasing"
                else -> "stable"
            }
        )
    }


    fun reset() {
        timePoints.clear()
        heartRates.clear()
        startTime = null // Reset start time
    }

    /**
     * Data class representing regression results.
     */
    data class RegressionResult(
        val slope: Double,      // BPM per second
        val intercept: Double,
        val rSquared: Double,   // Coefficient of determination (0.0 to 1.0)

        val trend: String       // "increasing", "decreasing", "stable"
    )

    fun predictAt(timeInSeconds: Double): Double? {
        return if (timePoints.size >= 2) {
            val regression = performRegression()
            regression.slope * timeInSeconds + regression.intercept
        } else {
            null
        }
    }
}