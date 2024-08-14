package com.gabstra.myworkoutassistant.data

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.gabstra.myworkoutassistant.repository.SensorDataRepository
import com.gabstra.myworkoutassistant.repository.MeasureMessageSensor
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

class SensorDataViewModel(
    private val sensorDataRepository: SensorDataRepository
) : ViewModel() {

    private val _heartRateAvailable = MutableStateFlow(false)
    val heartRateAvailable: StateFlow<Boolean> = _heartRateAvailable

    private val _heartRateBpm = MutableStateFlow<Int?>(null)
    val heartRateBpm: StateFlow<Int?> = _heartRateBpm

    private var heartRateCollectJob: Job? = null

    init {
        _heartRateAvailable.value = sensorDataRepository.hasHeartRateCapability()
    }

    @ExperimentalCoroutinesApi
    fun startMeasuringHeartRate() {
        stopMeasuringHeartRate()

        heartRateCollectJob = viewModelScope.launch {
            sensorDataRepository.heartBeatMeasureFlow()
                .collect { measureMessage ->
                    when (measureMessage) {
                        is MeasureMessageSensor.MeasureData -> {
                            _heartRateBpm.value = measureMessage.bpm
                        }
                        else -> {
                            // Handle other message types if needed
                        }
                    }
                }
        }
    }

    fun stopMeasuringHeartRate() {
        heartRateCollectJob?.cancel()
        heartRateCollectJob = null
    }

    override fun onCleared() {
        super.onCleared()
        stopMeasuringHeartRate()
    }
}

class SensorDataViewModelFactory(
    private val sensorDataRepository: SensorDataRepository
) : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        if (modelClass.isAssignableFrom(SensorDataViewModel::class.java)) {
            @Suppress("UNCHECKED_CAST")
            return SensorDataViewModel(
                sensorDataRepository = sensorDataRepository
            ) as T
        }
        throw IllegalArgumentException("Unknown ViewModel class")
    }
}
