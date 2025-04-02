package com.gabstra.myworkoutassistant.shared.viewmodels


import android.annotation.SuppressLint
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.gabstra.myworkoutassistant.shared.utils.HeartRateRegression
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import java.util.LinkedList
import kotlin.math.abs

class HeartRateChangeViewModel : ViewModel() {

    // Instance of the regression calculator
    private val heartRateRegression = HeartRateRegression()

    // State flow for the calculated rate of change (BPM per second)
    private val _heartRateChangeRate = MutableStateFlow<Float?>(null)
    val heartRateChangeRate: StateFlow<Float?> = _heartRateChangeRate

    // State flow for the confidence level (R² from regression, 0.0-1.0)
    private val _confidenceLevel = MutableStateFlow(0.0f)
    val confidenceLevel: StateFlow<Float> = _confidenceLevel

    // State flow for heart rate trend (with hysteresis/persistence)
    private val _heartRateTrend = MutableStateFlow<TrendDirection>(TrendDirection.UNKNOWN)
    val heartRateTrend: StateFlow<TrendDirection> = _heartRateTrend

    // State flow for formatted change rate
    private val _formattedChangeRate = MutableStateFlow("--")
    val formattedChangeRate: StateFlow<String> = _formattedChangeRate

    // Thresholds for determining significance of change (BPM/second)
    // Original was 18 BPM/min -> 18/60 = 0.3 BPM/s
    val significantIncreaseThreshold = 0.2f // BPM/s
    val significantDecreaseThreshold = -0.2f // BPM/s

    // Hysteresis buffer to prevent oscillation between states (BPM/s)
    // Adjust proportionally or use a suitable small value (e.g., 0.1 BPM/min -> ~0.0016 BPM/s, maybe 0.05 is better)
    private val hysteresisBuffer = 0.1f

    // Consecutive readings needed to confirm a trend
    private val requiredConsistentReadings = 3
    private var consistentReadingCounter = 0
    private var lastTrendDirection: TrendDirection = TrendDirection.UNKNOWN

    // Enum to represent trend direction
    enum class TrendDirection {
        INCREASING,
        DECREASING,
        STABLE,
        UNKNOWN
    }

    /**
     * Registers a new heart rate reading, performs regression, and updates state.
     */
    fun registerHeartRate(heartRate: Int) {
        viewModelScope.launch {
            // Only process valid heart rates
            if (heartRate <= 0) return@launch

            // Add reading to the regression model and get results
            val regressionResult = heartRateRegression.addReading(heartRate)

            if (regressionResult != null) {
                // Update state flows with regression results
                // Slope is BPM/second, round for display/consistency if desired
                val currentRate = (Math.round(regressionResult.slope * 1000) / 1000f).toFloat()
                _confidenceLevel.value = regressionResult.rSquared.toFloat()

                // Update trend direction using the calculated rate and hysteresis logic
                updateTrendDirection(currentRate)

            } else {
                // Not enough data points for regression yet
                _heartRateChangeRate.value = null
                _confidenceLevel.value = 0.0f
                // Reset trend if we don't have a calculation
                _heartRateTrend.value = TrendDirection.UNKNOWN
                consistentReadingCounter = 0
                lastTrendDirection = TrendDirection.UNKNOWN
            }

            // Update the formatted string regardless
            updateFormattedChangeRate()
        }
    }

    /**
     * Update trend direction with hysteresis and temporal persistence
     * Requires multiple consistent readings to confirm a trend.
     * Uses the calculated rate of change (BPM/s).
     */
    private fun updateTrendDirection(changeRate: Float) {
        // Skip if confidence (R²) is too low
        if (_confidenceLevel.value < 0.5f) { // Adjust confidence threshold if needed (e.g., 0.3 or 0.5)
            // Don't reset to UNKNOWN immediately if confidence dips briefly, maybe only if very low?
            // Let's reset for now if confidence is low.
            _heartRateTrend.value = TrendDirection.UNKNOWN
            consistentReadingCounter = 0
            _heartRateChangeRate.value = 0f
            // lastTrendDirection is not reset here to allow quick recovery if confidence improves
            return
        }

        // Determine the current raw trend based on thresholds and hysteresis
        val currentRawTrend = when {
            // If already INCREASING, stay INCREASING unless rate drops below threshold minus buffer
            _heartRateTrend.value == TrendDirection.INCREASING &&
                    changeRate >= (significantIncreaseThreshold - hysteresisBuffer) -> TrendDirection.INCREASING

            // If already DECREASING, stay DECREASING unless rate rises above threshold plus buffer
            _heartRateTrend.value == TrendDirection.DECREASING &&
                    changeRate <= (significantDecreaseThreshold + hysteresisBuffer) -> TrendDirection.DECREASING

            // Check for new INCREASING trend (must cross full threshold)
            changeRate >= significantIncreaseThreshold -> TrendDirection.INCREASING

            // Check for new DECREASING trend (must cross full threshold)
            changeRate <= significantDecreaseThreshold -> TrendDirection.DECREASING

            // Otherwise, it's STABLE
            else -> TrendDirection.STABLE
        }

        // Check for trend persistence
        if (currentRawTrend == lastTrendDirection) {
            consistentReadingCounter++
        } else {
            // Trend changed, reset counter and update last observed trend
            consistentReadingCounter = 1
            lastTrendDirection = currentRawTrend
        }

        // Only update the published trend if it has been consistent for enough readings
        // or if the new trend is STABLE (stable doesn't usually need confirmation)
        // or if the trend is UNKNOWN (which should be shown immediately)
        if (consistentReadingCounter >= requiredConsistentReadings || currentRawTrend == TrendDirection.STABLE) {
            if (_heartRateTrend.value != currentRawTrend){
                _heartRateTrend.value = currentRawTrend
            }
        }
        // If the counter is less than required, we don't change the public _heartRateTrend yet,
        // unless the current *public* trend is UNKNOWN, in which case we update immediately
        // to provide some initial feedback.
        else if (_heartRateTrend.value == TrendDirection.UNKNOWN){
            _heartRateTrend.value = currentRawTrend
        }

        _heartRateChangeRate.value = changeRate
    }


    /**
     * Reset stored readings and calculated rate by resetting the regression model
     * and the ViewModel's state.
     */
    fun reset() {
        viewModelScope.launch {
            heartRateRegression.reset() // Reset the underlying regression data
            // Reset ViewModel state
            consistentReadingCounter = 0
            lastTrendDirection = TrendDirection.UNKNOWN
            _heartRateChangeRate.value = null
            _confidenceLevel.value = 0.0f
            _heartRateTrend.value = TrendDirection.UNKNOWN
            _formattedChangeRate.value = "--"
        }
    }

    /**
     * Update formatted change rate string with current values.
     */
    @SuppressLint("DefaultLocale")
    private fun updateFormattedChangeRate() {
        val changeRate = _heartRateChangeRate.value // This is BPM/s
        val confidence = _confidenceLevel.value
        val trend = _heartRateTrend.value

        val trendIndicator = when (trend) {
            TrendDirection.INCREASING -> "↑"
            TrendDirection.DECREASING -> "↓"
            TrendDirection.STABLE -> "→"
            TrendDirection.UNKNOWN -> "?"
        }

        if(changeRate == null || trend == TrendDirection.UNKNOWN) {
            _formattedChangeRate.value = "--"
            return
        }

        val prefix = if (changeRate > 0) "+" else ""

        // Format rate to 1 or 2 decimal places for BPM/s
        val formattedRate = String.format("%.2f", changeRate).replace(',', '.')

        _formattedChangeRate.value = "$prefix${formattedRate}/s $trendIndicator"
    }
}