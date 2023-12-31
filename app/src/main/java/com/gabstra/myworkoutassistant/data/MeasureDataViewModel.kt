package com.gabstra.myworkoutassistant.data

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
        }
    }

    private fun startCollection(){
        if (collectionJob?.isActive != true) {
            collectionJob = viewModelScope.launch {
                healthServicesRepository.exerciseUpdateFlow().collect { it ->
                    when (it) {
                        is ExerciseMessage.ExerciseUpdateMessage ->{
                            processExerciseUpdate(it.exerciseUpdate)
                        }
                        is MeasureMessage.MeasureAvailability ->{
                        }
                    }
                }
            }

        }
    }

    private fun processExerciseUpdate(exerciseUpdate: ExerciseUpdate) {
        // Dismiss any ongoing activity notification.
        if(exerciseUpdate.exerciseStateInfo.state.isEnded){
            when (exerciseUpdate.exerciseStateInfo.endReason) {
                ExerciseEndReason.AUTO_END_SUPERSEDED -> {
                    // TODO Send the user a notification (another app ended their workout)
                    //Log.i("DEBUG","Your exercise was terminated because another app started tracking an exercise")
                }
                ExerciseEndReason.AUTO_END_MISSING_LISTENER -> {
                    // TODO Send the user a notification
                    //Log.i("DEBUG","Your exercise was auto ended because there were no registered listeners")
                }
                ExerciseEndReason.AUTO_END_PERMISSION_LOST -> {
                    // TODO Send the user a notification
                    //Log.w("DEBUG","Your exercise was auto ended because it lost the required permissions")
                }
                ExerciseEndReason.USER_END -> {

                }
                else -> {
                }
            }
        }
        //Log.i("DEBUG","BPM: "+exerciseUpdate.latestMetrics.getData(DataType.HEART_RATE_BPM).lastOrNull()?.value.toString())
        exerciseServiceState.update { old ->
            old.copy(
                exerciseState = ExerciseState.ACTIVE,//exerciseUpdate.exerciseStateInfo.state,
                exerciseMetrics = old.exerciseMetrics.update(exerciseUpdate.latestMetrics),
            )
        }
    }

    fun startExercise() {
        viewModelScope.launch{

            try{
                healthServicesRepository.prepareExercise()
                healthServicesRepository.startExercise()
            }catch (e: Exception) {
                Log.d("DEBUG","failed - ${e.message}")
            }

            startCollection()
            exerciseServiceState.update { old ->
                old.copy(
                    exerciseState = old.exerciseState,
                    exerciseMetrics = old.exerciseMetrics.copy(heartRate = null, heartRateAverage = null),
                )
            }
        }
    }

    fun endExercise() {
        viewModelScope.launch{
            try{
                //Log.d("EXERCISE DATA","on end")
                healthServicesRepository.endExercise()
                stopCollection()
            }catch (e: Exception) {
                //Log.d("EXERCISE DATA","on end failed - ${e.message}")
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
    val heartRate: Double? = null,
    val distance: Double? = null,
    val calories: Double? = null,
    val heartRateAverage: Double? = null,
) {
    fun update(latestMetrics: DataPointContainer): ExerciseMetrics {
        return copy(
            heartRate = latestMetrics.getData(DataType.HEART_RATE_BPM).lastOrNull()?.value
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