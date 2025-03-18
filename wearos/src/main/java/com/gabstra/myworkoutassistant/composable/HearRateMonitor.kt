package com.gabstra.myworkoutassistant.composable

import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.PolarViewModel
import com.gabstra.myworkoutassistant.data.SensorDataViewModel
import com.gabstra.myworkoutassistant.presentation.theme.MyColors
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.util.LinkedList
import kotlin.math.abs

/**
 * Handles heart rate change calculation logic with enhanced precision.
 * This class tracks heart rate measurements and applies statistical methods
 * to calculate a more precise rate of change.
 */
class HeartRateChangeCalculator {
    // Store recent heart rates with timestamps
    private val recentHeartRates = LinkedList<Pair<Long, Int>>()

    // Store filtered heart rates for noise reduction
    private val filteredHeartRates = LinkedList<Pair<Long, Double>>()

    // Store trend history for temporal smoothing
    private val trendHistory = LinkedList<Float>()

    // Maximum number of readings to store
    private val maxReadings = 20

    // Maximum history entries for trend smoothing
    private val maxTrendHistory = 5

    // Minimum time difference (ms) required for calculation
    private val minTimeDifferenceMs = 3000L

    // State flow for the calculated rate of change (BPM per second)
    private val _heartRateChangeRate = MutableStateFlow<Float?>(null)
    val heartRateChangeRate: StateFlow<Float?> = _heartRateChangeRate

    // State flow for the confidence level in the calculation (0.0-1.0)
    private val _confidenceLevel = MutableStateFlow(0.0f)
    val confidenceLevel: StateFlow<Float> = _confidenceLevel

    // State flow for heart rate trend
    private val _heartRateTrend = MutableStateFlow<TrendDirection>(TrendDirection.UNKNOWN)
    val heartRateTrend: StateFlow<TrendDirection> = _heartRateTrend

    // Thresholds for determining significance of change (BPM/s)
    val significantIncreaseThreshold = 0.3f // BPM/s - increased for stability
    val significantDecreaseThreshold = -0.3f // BPM/s - decreased for stability

    // Hysteresis buffer to prevent oscillation between states
    private val hysteresisBuffer = 0.1f

    // Consecutive readings needed to confirm a trend
    private val requiredConsistentReadings = 3
    private var consistentReadingCounter = 0
    private var lastTrendDirection: TrendDirection = TrendDirection.UNKNOWN

    // Alpha value for exponential moving average filter
    private val alphaEMA = 0.3

    // Exponential moving average of heart rate
    private var emaHeartRate = 0.0

    // Kalman filter parameters
    private var kalmanEstimate = 0.0
    private var kalmanError = 1.0
    private val kalmanProcessNoise = 0.01
    private val kalmanMeasurementNoise = 2.0

    // Enum to represent trend direction
    enum class TrendDirection {
        INCREASING,
        DECREASING,
        STABLE,
        UNKNOWN
    }

    /**
     * Registers a new heart rate reading and calculates the rate of change
     */
    fun registerHeartRate(heartRate: Int) {
        val currentTime = System.currentTimeMillis()

        // Only add non-zero heart rates
        if (heartRate <= 0) return

        // Apply Kalman filter to reduce noise
        val filteredValue = applyKalmanFilter(heartRate.toDouble())

        // Apply exponential moving average for additional smoothing
        updateEMA(filteredValue)

        // Add new raw reading
        recentHeartRates.add(Pair(currentTime, heartRate))

        // Add filtered reading (using the EMA value for better smoothing)
        filteredHeartRates.add(Pair(currentTime, emaHeartRate))

        // Keep only the most recent readings
        while (recentHeartRates.size > maxReadings) {
            recentHeartRates.removeFirst()
        }

        while (filteredHeartRates.size > maxReadings) {
            filteredHeartRates.removeFirst()
        }

        // Calculate rate of change using best method based on data availability
        calculateHeartRateChangeRate()
    }

    /**
     * Update exponential moving average with new filtered heart rate
     */
    private fun updateEMA(newValue: Double) {
        if (emaHeartRate == 0.0) {
            // Initialize EMA with first value
            emaHeartRate = newValue
        } else {
            // Update EMA with new value
            emaHeartRate = alphaEMA * newValue + (1 - alphaEMA) * emaHeartRate
        }
    }

    /**
     * Apply Kalman filter to reduce noise in heart rate measurements
     */
    private fun applyKalmanFilter(measurement: Double): Double {
        // Prediction update
        val predictionError = kalmanError + kalmanProcessNoise

        // Measurement update
        val kalmanGain = predictionError / (predictionError + kalmanMeasurementNoise)
        kalmanEstimate += kalmanGain * (measurement - kalmanEstimate)
        kalmanError = (1 - kalmanGain) * predictionError

        return kalmanEstimate
    }

    /**
     * Calculates rate of change in BPM per second based on stored readings
     * using several statistical methods for improved precision
     */
    private fun calculateHeartRateChangeRate() {
        // Need at least 3 readings for better precision
        if (filteredHeartRates.size < 3) {
            _heartRateChangeRate.value = null
            _confidenceLevel.value = 0.0f
            _heartRateTrend.value = TrendDirection.UNKNOWN
            return
        }

        // Apply linear regression for better precision
        val result = calculateLinearRegression()

        // Variable to store the calculated change rate
        var calculatedRate: Float? = null

        // If we have enough points, use linear regression slope
        if (result != null) {
            // Slope is in BPM/ms, convert to BPM/s
            val changeRatePerSecond = result.first * 1000

            // Set confidence level based on R² value
            _confidenceLevel.value = result.second.toFloat()

            // Round to three decimal places for better precision
            calculatedRate = (Math.round(changeRatePerSecond * 1000) / 1000f)
        } else {
            // Fallback to simpler calculation if regression fails
            calculatedRate = fallbackCalculation()
        }

        // Add to trend history for temporal smoothing
        if (calculatedRate != null) {
            trendHistory.add(calculatedRate)

            // Keep only recent history
            while (trendHistory.size > maxTrendHistory) {
                trendHistory.removeFirst()
            }

            // Apply temporal smoothing across trend history
            val smoothedRate = smoothTrendRate()
            _heartRateChangeRate.value = smoothedRate

            // Classify the trend with hysteresis and persistence
            updateTrendDirection(smoothedRate)
        }
    }

    /**
     * Apply temporal smoothing to trend rate using a weighted average
     * More recent values have higher weight
     */
    private fun smoothTrendRate(): Float {
        if (trendHistory.isEmpty()) return 0f

        var weightedSum = 0f
        var weightSum = 0f

        // Apply weighted average with more recent values having higher weights
        trendHistory.forEachIndexed { index, rate ->
            val weight = index + 1 // Linear weight increase
            weightedSum += rate * weight
            weightSum += weight
        }

        return if (weightSum > 0) {
            (Math.round((weightedSum / weightSum) * 1000) / 1000f)
        } else {
            trendHistory.last()
        }
    }

    /**
     * Update trend direction with hysteresis and temporal persistence
     * Requires multiple consistent readings to confirm a trend
     */
    private fun updateTrendDirection(changeRate: Float) {
        // Skip if confidence is too low
        if (_confidenceLevel.value < 0.5f) {
            _heartRateTrend.value = TrendDirection.UNKNOWN
            consistentReadingCounter = 0
            return
        }

        // Determine the current trend with hysteresis to prevent oscillation
        val currentTrend = when {
            // If currently increasing, keep increasing unless it drops below threshold minus buffer
            _heartRateTrend.value == TrendDirection.INCREASING &&
                    changeRate >= (significantIncreaseThreshold - hysteresisBuffer) -> TrendDirection.INCREASING

            // If currently decreasing, keep decreasing unless it rises above threshold plus buffer
            _heartRateTrend.value == TrendDirection.DECREASING &&
                    changeRate <= (significantDecreaseThreshold + hysteresisBuffer) -> TrendDirection.DECREASING

            // New increasing trend must cross the full threshold
            changeRate >= significantIncreaseThreshold -> TrendDirection.INCREASING

            // New decreasing trend must cross the full threshold
            changeRate <= significantDecreaseThreshold -> TrendDirection.DECREASING

            // Otherwise stable
            else -> TrendDirection.STABLE
        }

        // Check for trend persistence
        if (currentTrend == lastTrendDirection) {
            consistentReadingCounter++
        } else {
            consistentReadingCounter = 1
            lastTrendDirection = currentTrend
        }

        // Only update the published trend if we have enough consistent readings
        if (consistentReadingCounter >= requiredConsistentReadings) {
            _heartRateTrend.value = currentTrend
        }
    }

    /**
     * Calculate linear regression on filtered heart rate data
     * Returns pair of (slope, R² value) or null if calculation fails
     */
    private fun calculateLinearRegression(): Pair<Double, Double>? {
        try {
            val n = filteredHeartRates.size

            // Extract x (time in ms, normalized to start at 0) and y (heart rate) values
            val startTime = filteredHeartRates.first.first
            val x = filteredHeartRates.map { (it.first - startTime).toDouble() }.toDoubleArray()
            val y = filteredHeartRates.map { it.second }.toDoubleArray()

            // Calculate means
            val meanX = x.average()
            val meanY = y.average()

            // Calculate sum of squares
            var sumXY = 0.0
            var sumXX = 0.0
            var sumYY = 0.0

            for (i in 0 until n) {
                val xDiff = x[i] - meanX
                val yDiff = y[i] - meanY
                sumXY += xDiff * yDiff
                sumXX += xDiff * xDiff
                sumYY += yDiff * yDiff
            }

            // Avoid division by zero
            if (sumXX == 0.0 || sumYY == 0.0) return null

            // Calculate slope and R²
            val slope = sumXY / sumXX
            val rSquared = (sumXY * sumXY) / (sumXX * sumYY)

            return Pair(slope, rSquared)
        } catch (e: Exception) {
            // If anything goes wrong, return null
            return null
        }
    }

    /**
     * Fallback calculation method when linear regression is not possible
     */
    private fun fallbackCalculation(): Float? {
        // Get filtered readings
        val oldest = filteredHeartRates.first
        val newest = filteredHeartRates.last

        val timeDifferenceMs = newest.first - oldest.first

        // Ensure meaningful time difference
        if (timeDifferenceMs < minTimeDifferenceMs) {
            _confidenceLevel.value = 0.0f
            return null
        }

        // Calculate change in BPM using filtered values
        val bpmDifference = newest.second - oldest.second

        // Convert to BPM change per second
        val changeRatePerSecond = (bpmDifference / timeDifferenceMs) * 1000

        // Lower confidence level for fallback method
        _confidenceLevel.value = 0.5f

        // Round to three decimal places
        return (Math.round(changeRatePerSecond * 1000) / 1000f)
    }

    /**
     * Reset stored readings and calculated rate
     */
    fun reset() {
        recentHeartRates.clear()
        filteredHeartRates.clear()
        trendHistory.clear()
        kalmanEstimate = 0.0
        kalmanError = 1.0
        emaHeartRate = 0.0
        consistentReadingCounter = 0
        lastTrendDirection = TrendDirection.UNKNOWN
        _heartRateChangeRate.value = null
        _confidenceLevel.value = 0.0f
        _heartRateTrend.value = TrendDirection.UNKNOWN
    }

    /**
     * Get a formatted string with rate of change, confidence indicator and trend
     */
    fun getFormattedChangeRate(): String {
        val changeRate = _heartRateChangeRate.value

        if (changeRate == null) {
            return "Δ: --"
        }

        val prefix = if (changeRate > 0) "+" else ""
        val confidenceIndicator = when {
            _confidenceLevel.value > 0.8f -> "***" // High confidence
            _confidenceLevel.value > 0.5f -> "**"  // Medium confidence
            else -> "*"                           // Low confidence
        }

        val trendIndicator = when (_heartRateTrend.value) {
            TrendDirection.INCREASING -> "↑"
            TrendDirection.DECREASING -> "↓"
            TrendDirection.STABLE -> "→"
            TrendDirection.UNKNOWN -> "?"
        }

        return "Δ: $prefix${changeRate}/s $confidenceIndicator $trendIndicator"
    }
}

/**
 * Composable that handles heart rate monitoring and change rate calculation
 */
@Composable
fun HeartRateMonitor(
    appViewModel: AppViewModel,
    heartRateSupplier: () -> Int
) {
    // Create and remember the calculator
    val calculator = remember { HeartRateChangeCalculator() }

    // Observe the change rate and confidence
    val changeRate by calculator.heartRateChangeRate.collectAsState()
    val confidence by calculator.confidenceLevel.collectAsState()

    // Update the change rate in the app view model with confidence level and trend
    LaunchedEffect(changeRate, confidence) {
        appViewModel.updateHeartRateChangeRate(changeRate, confidence )
    }

    // Poll for heart rate readings
    LaunchedEffect(Unit) {
        while (true) {
            val hr = heartRateSupplier()
            calculator.registerHeartRate(hr)
            delay(1000)
        }
    }

    // Clean up when leaving composition
    DisposableEffect(Unit) {
        onDispose {
            calculator.reset()
        }
    }
}