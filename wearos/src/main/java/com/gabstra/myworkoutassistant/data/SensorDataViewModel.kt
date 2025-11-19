package com.gabstra.myworkoutassistant.data

import android.content.Context
import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.gabstra.myworkoutassistant.MyApplication
import com.gabstra.myworkoutassistant.repository.SensorDataRepository
import kotlinx.coroutines.CoroutineExceptionHandler
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

class SensorDataViewModel(
    private val sensorDataRepository: SensorDataRepository
) : ViewModel() {
    
    private var applicationContext: Context? = null
    
    fun initApplicationContext(context: Context) {
        applicationContext = context.applicationContext
    }
    
    private val coroutineExceptionHandler = CoroutineExceptionHandler { _, throwable ->
        Log.e("SensorDataViewModel", "Uncaught exception in coroutine", throwable)
        // Log the exception to file via MyApplication if available
        try {
            (applicationContext as? MyApplication)?.logErrorToFile("SensorDataViewModel Coroutine", throwable)
        } catch (e: Exception) {
            Log.e("SensorDataViewModel", "Failed to log exception to file", e)
        }
    }

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

        heartRateCollectJob = viewModelScope.launch(coroutineExceptionHandler) {
            try {
                sensorDataRepository.heartBeatMeasureFlow()
                    .collect { measureMessage ->
                        try {
                            when (measureMessage) {
                                else -> {
                                    _heartRateBpm.value = measureMessage.bpm
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
