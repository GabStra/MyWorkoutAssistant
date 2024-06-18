package com.gabstra.myworkoutassistant.data

import android.util.Log
import androidx.health.services.client.data.DataTypeAvailability
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.gabstra.myworkoutassistant.repository.MeasureDataRepository
import com.gabstra.myworkoutassistant.repository.MeasureMessage
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

class MeasureDataViewModel(
    private val measureDataRepository: MeasureDataRepository
) : ViewModel() {

    private val _heartRateAvailable = MutableStateFlow(DataTypeAvailability.UNKNOWN)
    val heartRateAvailable: StateFlow<DataTypeAvailability> = _heartRateAvailable

    private val _heartRateBpm = MutableStateFlow<Int?>(null)
    val heartRateBpm: StateFlow<Int?> = _heartRateBpm

    private var heartRateCollectJob: Job? = null

    @ExperimentalCoroutinesApi
    fun startMeasuringHeartRate() {
        // Cancel any existing collection job to ensure we don't have multiple collectors
        stopMeasuringHeartRate()

        heartRateCollectJob = viewModelScope.launch {
            measureDataRepository.heartRateMeasureFlow()
                .collect { measureMessage ->
                    when (measureMessage) {
                        is MeasureMessage.MeasureAvailability -> {
                            _heartRateAvailable.value = measureMessage.availability
                        }
                        is MeasureMessage.MeasureData -> {
                            val latestHeartRate = measureMessage.data
                                .map { it.value.toInt() }
                                .last() // Get the latest data point

                            if(latestHeartRate != 0) {
                                _heartRateBpm.value = latestHeartRate
                            }
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
        // Ensure all children coroutines are cancelled when the ViewModel is cleared
        stopMeasuringHeartRate()
    }
}

class MeasureDataViewModelFactory(
    private val measureDataRepository: MeasureDataRepository
) : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        if (modelClass.isAssignableFrom(MeasureDataViewModel::class.java)) {
            @Suppress("UNCHECKED_CAST")
            return MeasureDataViewModel(
                measureDataRepository = measureDataRepository
            ) as T
        }
        throw IllegalArgumentException("Unknown ViewModel class")
    }
}

sealed class UiState {
    object Startup : UiState()
    object HeartRateAvailable : UiState()
    object HeartRateNotAvailable : UiState()
}

/*
import android.util.Log
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.mutableStateOf
import androidx.health.services.client.data.DataPointContainer
import androidx.health.services.client.data.DataType
import androidx.health.services.client.data.DataTypeAvailability
import androidx.health.services.client.data.ExerciseEndReason
import androidx.health.services.client.data.ExerciseState
import androidx.health.services.client.data.ExerciseType
import androidx.health.services.client.data.ExerciseUpdate
import androidx.health.services.client.data.LocationAvailability
import androidx.health.services.client.proto.DataProto
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.takeWhile
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import androidx.health.services.client.data.ExerciseUpdate.ActiveDurationCheckpoint
import androidx.health.services.client.data.LocationData
import androidx.health.services.client.data.WarmUpConfig
import androidx.health.services.client.prepareExercise
import com.gabstra.myworkoutassistant.repository.ExerciseMessage
import com.gabstra.myworkoutassistant.repository.HealthServicesRepository
import com.gabstra.myworkoutassistant.repository.MeasureMessage
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay

class MeasureDataViewModel(
    private val healthServicesRepository: HealthServicesRepository,
) : ViewModel() {
    val exerciseServiceState = MutableStateFlow(
        ExerciseServiceState(
            exerciseState = null,
            exerciseMetrics = ExerciseMetrics()
        )
    )
    private var collectionJob: Job? = null

    val uiState: MutableState<UiState> = mutableStateOf(UiState.Startup)

    init {
        viewModelScope.launch {
            val supported = healthServicesRepository.getExerciseCapabilities()

            uiState.value = if (supported != null) {
                UiState.Supported
            } else {
                UiState.NotSupported
            }
        }
    }

    private fun stopCollection(){
        if (collectionJob?.isActive == true) {
            collectionJob?.cancel()
            collectionJob = null
        }
    }

    private fun startCollection(){
        if (collectionJob?.isActive != true) {
            collectionJob = viewModelScope.launch {
                healthServicesRepository.exerciseUpdateFlow().collect { it ->
                    if(it is ExerciseMessage.ExerciseUpdateMessage) {
                        processExerciseUpdate(it.exerciseUpdate)
                    }
                }
            }

        }
    }

    private fun processExerciseUpdate(exerciseUpdate: ExerciseUpdate) {
        // Dismiss any ongoing activity notification.
        if(exerciseUpdate.exerciseStateInfo.state.isEnded){
            return
        }

        exerciseServiceState.update { old ->
            old.copy(
                exerciseState = ExerciseState.ACTIVE,//exerciseUpdate.exerciseStateInfo.state,
                exerciseMetrics = old.exerciseMetrics.update(exerciseUpdate.latestMetrics),
            )
        }
    }

    fun startExercise() {
        viewModelScope.launch{
            startCollection()

            try{
                healthServicesRepository.prepareExercise()
            }catch (e: Exception) {
                //Log.d("MeasureData","failed - ${e.message}")
            }


        }
    }

    fun endExercise() {
        viewModelScope.launch{
            try{
                //healthServicesRepository.endExercise()

                exerciseServiceState.update { old ->
                    old.copy(
                        exerciseState =  null,
                        exerciseMetrics = ExerciseMetrics(),
                    )
                }
                stopCollection()
            }catch (e: Exception) {
            }
        }
    }

}

class MeasureDataViewModelFactory(
    private val healthServicesRepository: HealthServicesRepository
) : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        if (modelClass.isAssignableFrom(MeasureDataViewModel::class.java)) {
            @Suppress("UNCHECKED_CAST")
            return MeasureDataViewModel(
                healthServicesRepository = healthServicesRepository
            ) as T
        }
        throw IllegalArgumentException("Unknown ViewModel class")
    }
}

sealed class UiState {
    object Startup : UiState()
    object NotSupported : UiState()
    object Supported : UiState()
}
data class ExerciseMetrics(
    val heartRate: Int? = null,
    val distance: Double? = null,
    val calories: Double? = null,
    val heartRateAverage: Double? = null,
) {
    fun update(latestMetrics: DataPointContainer): ExerciseMetrics {
        return copy(
            heartRate = latestMetrics.getData(DataType.HEART_RATE_BPM).lastOrNull()?.value?.toInt()
                ?: heartRate,
            heartRateAverage = latestMetrics.getData(DataType.HEART_RATE_BPM_STATS)?.average
                ?: heartRateAverage,
        )
    }
}

data class ExerciseServiceState(
    val exerciseState: ExerciseState? = null,
    val exerciseMetrics: ExerciseMetrics = ExerciseMetrics(),
)
*/