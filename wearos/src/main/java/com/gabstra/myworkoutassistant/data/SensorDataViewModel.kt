package com.gabstra.myworkoutassistant.data

import android.content.Context
import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.gabstra.myworkoutassistant.MyApplication
import com.gabstra.myworkoutassistant.repository.SamsungHeartRatePreferences
import com.gabstra.myworkoutassistant.repository.SamsungSensorDataRepository
import com.gabstra.myworkoutassistant.repository.SensorDataRepository
import kotlin.coroutines.EmptyCoroutineContext
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

class SensorDataViewModel(
    private val sensorDataRepository: SensorDataRepository,
    private val samsungSensorDataRepository: SamsungSensorDataRepository? = null
) : ViewModel() {
    
    private var applicationContext: Context? = null
    
    fun initApplicationContext(context: Context) {
        applicationContext = context.applicationContext
        refreshHeartRateAvailability()
    }

    private val appCeh get() = (applicationContext as? MyApplication)?.coroutineExceptionHandler ?: EmptyCoroutineContext

    private val _heartRateAvailable = MutableStateFlow(false)
    val heartRateAvailable: StateFlow<Boolean> = _heartRateAvailable

    private val _heartRateBpm = MutableStateFlow<Int?>(null)
    val heartRateBpm: StateFlow<Int?> = _heartRateBpm

    /** Latest sample's beat-to-beat intervals (ms); empty on the stock sensor path. */
    private val _heartRateIbi = MutableStateFlow<List<Int>>(emptyList())
    val heartRateIbi: StateFlow<List<Int>> = _heartRateIbi

    private var heartRateCollectJob: Job? = null

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

    @ExperimentalCoroutinesApi
    fun startMeasuringHeartRate() {
        stopMeasuringHeartRate()

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
    }

    fun stopMeasuringHeartRate() {
        heartRateCollectJob?.cancel()
        heartRateCollectJob = null
    }

    override fun onCleared() {
        stopMeasuringHeartRate()
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
