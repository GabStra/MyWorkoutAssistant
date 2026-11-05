package com.gabstra.myworkoutassistant.samsung

import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow

enum class SamsungTrackerType {
    HEART_RATE_CONTINUOUS, PPG_CONTINUOUS, SPO2_CONTINUOUS,
    SKIN_TEMPERATURE_ON_DEMAND, SWEAT_LOSS, ACCELEROMETER_CONTINUOUS,
    ECG_ON_DEMAND, BIA_ON_DEMAND, EDA_CONTINUOUS
}

data class TrackerProfile(val heightCm: Int, val weightKg: Float, val age: Int, val gender: Int)

sealed interface SamsungSample {
    val timestampMs: Long
    data class HeartRate(val bpm: Int, val ibiList: List<Int>, val status: Int?, override val timestampMs: Long) : SamsungSample
    data class Ppg(val status: Int?, val green: IntArray?, val ir: IntArray?, val red: IntArray?, override val timestampMs: Long) : SamsungSample
    data class SpO2(val percent: Int, val status: Int?, override val timestampMs: Long) : SamsungSample
    data class SkinTemperature(val celsius: Float, override val timestampMs: Long) : SamsungSample
    data class SweatLoss(val ml: Int, override val timestampMs: Long) : SamsungSample
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
    /** Cold flow: collecting activates the tracker, cancelling unsets its listener. */
    fun samples(type: SamsungTrackerType): Flow<SamsungSample>
}
