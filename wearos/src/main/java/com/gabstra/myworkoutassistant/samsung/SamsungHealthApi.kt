package com.gabstra.myworkoutassistant.samsung

import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow

enum class SamsungTrackerType {
    HEART_RATE_CONTINUOUS, PPG_CONTINUOUS, SPO2_CONTINUOUS,
    SKIN_TEMPERATURE_ON_DEMAND, SKIN_TEMPERATURE_CONTINUOUS, SWEAT_LOSS, ACCELEROMETER_CONTINUOUS,
    ECG_ON_DEMAND, BIA_ON_DEMAND, EDA_CONTINUOUS
}

data class TrackerProfile(val heightCm: Int, val weightKg: Float, val age: Int, val gender: Int)

sealed interface SamsungSample {
    val timestampMs: Long
    data class HeartRate(
        val bpm: Int,
        val ibiList: List<Int>,
        val status: Int?,
        override val timestampMs: Long,
        /** Per-interval quality flags aligned with [ibiList]. */
        val ibiStatusList: List<Int> = emptyList(),
    ) : SamsungSample
    data class Ppg(val status: Int?, val green: IntArray?, val ir: IntArray?, val red: IntArray?, override val timestampMs: Long) : SamsungSample
    data class SpO2(val percent: Int, val status: Int?, override val timestampMs: Long) : SamsungSample
    data class SkinTemperature(
        val celsius: Float,
        override val timestampMs: Long,
        val ambientCelsius: Float? = null,
        /** SemSkinTemperatureSensorParam.Accuracy: 0 = normal, -1 = error. */
        val status: Int? = null,
    ) : SamsungSample
    data class SweatLoss(
        val ml: Int,
        override val timestampMs: Long,
        /** SweatLoss status: 0 = ok, -4 = auto-ended (value still valid), other = error. */
        val status: Int = 0,
    ) : SamsungSample
    data class Accelerometer(val x: Float, val y: Float, val z: Float, override val timestampMs: Long) : SamsungSample
    data class Ecg(val mv: List<Float>, override val timestampMs: Long) : SamsungSample
    data class Bia(val impedance: Float?, override val timestampMs: Long) : SamsungSample
    data class Eda(val value: Int, override val timestampMs: Long) : SamsungSample
}

sealed interface SamsungConnectionState {
    data object Disconnected : SamsungConnectionState
    data object Connecting : SamsungConnectionState
    data object Connected : SamsungConnectionState
    data class Failed(val message: String) : SamsungConnectionState
}

interface SamsungHealthTrackerClient {
    val connectionState: StateFlow<SamsungConnectionState>
    val errorEvents: SharedFlow<String>
    suspend fun connect(profile: TrackerProfile? = null)
    suspend fun disconnect()
    suspend fun availableTrackers(): Set<SamsungTrackerType>
    /**
     * Selects the PPG LED set for [type]; Samsung's names are "GREEN", "IR", "RED".
     *
     * Verified in the HealthPlatform decompile: only the PPG trackers implement it
     * (BaseTracker.setPpgType is a no-op; PpgContinuous/PpgOnDemand add the channels to the
     * sensor setting at registration). Call it before collecting samples.
     */
    suspend fun setPpgType(type: SamsungTrackerType, ppgTypes: List<String>)
    /** Cold flow: collecting activates the tracker, cancelling unsets its listener. */
    fun samples(type: SamsungTrackerType): Flow<SamsungSample>
}
