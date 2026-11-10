package com.gabstra.myworkoutassistant.data

import android.content.Context
import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.gabstra.myworkoutassistant.MyApplication
import com.gabstra.myworkoutassistant.repository.MeasureMessageSensor
import com.gabstra.myworkoutassistant.repository.SamsungHeartRatePreferences
import com.gabstra.myworkoutassistant.repository.SamsungSensorDataRepository
import com.gabstra.myworkoutassistant.repository.SensorDataRepository
import kotlin.coroutines.EmptyCoroutineContext
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.launch

class SensorDataViewModel(
    private val sensorDataRepository: SensorDataRepository,
    private val samsungSensorDataRepository: SamsungSensorDataRepository? = null
) : ViewModel() {

    private var applicationContext: Context? = null
    
    fun initApplicationContext(context: Context) {
        applicationContext = context.applicationContext
        refreshHeartRateAvailability()
        observeSamsungToggle()
    }

    private val appCeh get() = (applicationContext as? MyApplication)?.coroutineExceptionHandler ?: EmptyCoroutineContext

    private val _heartRateAvailable = MutableStateFlow(false)
    val heartRateAvailable: StateFlow<Boolean> = _heartRateAvailable

    private val _heartRateBpm = MutableStateFlow<Int?>(null)
    val heartRateBpm: StateFlow<Int?> = _heartRateBpm

    /** Latest sample's beat-to-beat intervals (ms); empty on the stock sensor path. */
    private val _heartRateIbi = MutableStateFlow<List<Int>>(emptyList())
    val heartRateIbi: StateFlow<List<Int>> = _heartRateIbi

    /** Latest sensor-reported HR quality status; null on the stock sensor path. */
    private val _heartRateStatus = MutableStateFlow<Int?>(null)
    val heartRateStatus: StateFlow<Int?> = _heartRateStatus

    /**
     * Samples received since the current measuring run started. Reset on every
     * [startMeasuringHeartRate], so preparing can tell a live sensor from a stale BPM value.
     */
    private val _heartRateSampleCount = MutableStateFlow(0)
    val heartRateSampleCount: StateFlow<Int> = _heartRateSampleCount

    /**
     * Every tracker sample, push-based. History and HRV must see each sample; the chart's 1 Hz
     * tick is only a UI display cadence and would drop whatever arrives faster.
     */
    private val _heartRateSamples = MutableSharedFlow<MeasureMessageSensor.MeasureData>(
        extraBufferCapacity = 8,
        onBufferOverflow = BufferOverflow.DROP_OLDEST,
    )
    val heartRateSamples: SharedFlow<MeasureMessageSensor.MeasureData> = _heartRateSamples.asSharedFlow()



    /** Latest raw sweat-loss sample in ml (not accumulated); null while unavailable. */
    private val _sweatLossMl = MutableStateFlow<Int?>(null)
    val sweatLossMl: StateFlow<Int?> = _sweatLossMl

    /** Continuous skin temperature (Celsius); null while unavailable. */
    private val _skinTempCelsius = MutableStateFlow<Float?>(null)
    val skinTempCelsius: StateFlow<Float?> = _skinTempCelsius

    /**
     * True only while the Samsung aux trackers are actually running. Sweat loss and skin
     * temperature do not exist on the stock sensor path, so consumers must not collect them
     * just because the flows exist.
     */
    private val _auxSensorsAvailable = MutableStateFlow(false)
    val auxSensorsAvailable: StateFlow<Boolean> = _auxSensorsAvailable

    private var heartRateCollectJob: Job? = null
    private var sweatLossCollectJob: Job? = null
    private var skinTempCollectJob: Job? = null
    private var samsungToggleCollectJob: Job? = null

    init {
        refreshHeartRateAvailability()
    }

    /**
     * Runtime switch: uses the Samsung Health backed repository only while the
     * [SamsungHeartRatePreferences] toggle is enabled, falling back to the stock
     * Android sensor repository otherwise (default behavior).
     */
    private fun usesSamsungRepository(): Boolean {
        val context = applicationContext ?: return false
        return samsungSensorDataRepository != null &&
            SamsungHeartRatePreferences.isSamsungHeartRateEnabled(context)
    }

    private fun refreshHeartRateAvailability() {
        _heartRateAvailable.value = if (usesSamsungRepository()) {
            samsungSensorDataRepository?.hasHeartRateCapability() == true
        } else {
            sensorDataRepository.hasHeartRateCapability()
        }
    }

    /** Keeps the Samsung-only collectors tied to the runtime toggle, which the user can flip mid-session. */
    private fun observeSamsungToggle() {
        val context = applicationContext ?: return
        if (samsungToggleCollectJob?.isActive == true) return
        samsungToggleCollectJob = viewModelScope.launch(appCeh) {
            try {
                SamsungHeartRatePreferences.enabledChanges(context).collect { enabled ->
                    if (enabled) {
                        // Aux sensors are workout-scoped: only collect while HR measurement runs.
                        if (heartRateCollectJob?.isActive == true) startSamsungAuxCollectors()
                    } else {
                        stopSamsungAuxCollectors()
                    }
                }
            } catch (e: Exception) {
                Log.e("SensorDataViewModel", "Error observing Samsung heart rate toggle", e)
            }
        }
    }

    private fun startSamsungAuxCollectors() {
        val repository = samsungSensorDataRepository ?: return
        if (!usesSamsungRepository()) return
        _auxSensorsAvailable.value = true

        sweatLossCollectJob?.cancel()
        sweatLossCollectJob = viewModelScope.launch(appCeh) {
            try {
                repository.sweatLossSamples().collect { sample -> _sweatLossMl.value = sample.ml }
            } catch (e: Exception) {
                Log.e("SensorDataViewModel", "Error collecting sweat loss samples", e)
            }
        }

        skinTempCollectJob?.cancel()
        skinTempCollectJob = viewModelScope.launch(appCeh) {
            try {
                repository.skinTemperatureSamples().collect { sample ->
                    // Accuracy 0 = normal; only plausible wrist temperatures are published.
                    if ((sample.status == null || sample.status == 0) &&
                        sample.celsius in 20f..45f
                    ) {
                        _skinTempCelsius.value = sample.celsius
                    }
                }
            } catch (e: Exception) {
                Log.e("SensorDataViewModel", "Error collecting skin temperature", e)
            }
        }
    }

    private fun stopSamsungAuxCollectors() {
        sweatLossCollectJob?.cancel()
        sweatLossCollectJob = null
        skinTempCollectJob?.cancel()
        skinTempCollectJob = null
        _auxSensorsAvailable.value = false
        _sweatLossMl.value = null
        _skinTempCelsius.value = null
    }

    @ExperimentalCoroutinesApi
    fun startMeasuringHeartRate() {
        stopMeasuringHeartRate()
        _heartRateSampleCount.value = 0

        heartRateCollectJob = viewModelScope.launch(appCeh) {
            try {
                refreshHeartRateAvailability()

                val measureFlow = if (usesSamsungRepository()) {
                    samsungSensorDataRepository?.heartBeatMeasureFlow()
                } else {
                    sensorDataRepository.heartBeatMeasureFlow()
                }
                if (measureFlow == null) {
                    Log.e("SensorDataViewModel", "Heart rate repository unavailable")
                    return@launch
                }

                measureFlow.collect { measureMessage ->
                    try {
                        when (measureMessage) {
                            else -> {
                                _heartRateBpm.value = measureMessage.bpm
                                _heartRateIbi.value = measureMessage.ibiList
                                _heartRateStatus.value = measureMessage.heartRateStatus
                                _heartRateSampleCount.value = _heartRateSampleCount.value + 1
                                _heartRateSamples.tryEmit(measureMessage)
                            }
                        }
                    } catch (e: Exception) {
                        Log.e("SensorDataViewModel", "Error processing heart rate measurement", e)
                    }
                }
            } catch (e: Exception) {
                Log.e("SensorDataViewModel", "Error starting heart rate measurement", e)
            }
        }
        if (usesSamsungRepository()) startSamsungAuxCollectors()
    }

    fun stopMeasuringHeartRate() {
        heartRateCollectJob?.cancel()
        heartRateCollectJob = null
        stopSamsungAuxCollectors()
    }

    override fun onCleared() {
        stopMeasuringHeartRate()
        stopSamsungAuxCollectors()
        samsungToggleCollectJob?.cancel()
        samsungToggleCollectJob = null
    }
}

class SensorDataViewModelFactory(
    private val sensorDataRepository: SensorDataRepository,
    private val samsungSensorDataRepository: SamsungSensorDataRepository? = null
) : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        if (modelClass.isAssignableFrom(SensorDataViewModel::class.java)) {
            @Suppress("UNCHECKED_CAST")
            return SensorDataViewModel(
                sensorDataRepository = sensorDataRepository,
                samsungSensorDataRepository = samsungSensorDataRepository
            ) as T
        }
        throw IllegalArgumentException("Unknown ViewModel class")
    }
}
