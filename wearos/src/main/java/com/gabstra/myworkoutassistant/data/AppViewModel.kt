package com.gabstra.myworkoutassistant.data

import android.content.Context
import android.widget.Toast
import androidx.compose.runtime.State
import androidx.compose.runtime.asIntState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.viewModelScope
import com.gabstra.myworkoutassistant.MyApplication
import com.gabstra.myworkoutassistant.shared.ExerciseInfo
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgression
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryStore
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.Node
import android.util.Log
import kotlinx.coroutines.CoroutineExceptionHandler
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.UUID

open class AppViewModel : WorkoutViewModel() {
    
    private var applicationContext: android.content.Context? = null
    
    fun initApplicationContext(context: android.content.Context) {
        applicationContext = context.applicationContext
    }
    
    private val coroutineExceptionHandler = CoroutineExceptionHandler { _, throwable ->
        Log.e("AppViewModel", "Uncaught exception in coroutine", throwable)
        // Log the exception to file via MyApplication if available
        try {
            (applicationContext as? MyApplication)?.logErrorToFile("AppViewModel Coroutine", throwable)
        } catch (e: Exception) {
            Log.e("AppViewModel", "Failed to log exception to file", e)
        }
    }
    private var dataClient: DataClient? = null
    var phoneNode by mutableStateOf<Node?>(null)

    val isPhoneConnectedAndHasApp: Boolean
        get() = phoneNode != null

    fun initDataClient(client: DataClient) {
        dataClient = client
    }

    private val _executeStartWorkout = mutableStateOf<UUID?>(null)
    val executeStartWorkout: State<UUID?> = _executeStartWorkout

    // Method to trigger the action
    fun triggerStartWorkout(globalId: UUID) {
        _executeStartWorkout.value = globalId
    }

    // Method to reset/consume the action
    fun consumeStartWorkout() {
        _executeStartWorkout.value = null
    }

    private val _hrDisplayMode = mutableStateOf(0)
    val hrDisplayMode: State<Int> = _hrDisplayMode.asIntState()
    private val _headerDisplayMode = mutableStateOf(0)
    val headerDisplayMode: State<Int> = _headerDisplayMode.asIntState()

    fun switchHrDisplayMode() {
        _hrDisplayMode.value = (_hrDisplayMode.value + 1) % 2
    }

    fun switchHeaderDisplayMode() {
        _headerDisplayMode.value = (_headerDisplayMode.value + 1) % 2
    }

    fun sendAll(context: Context) {
        viewModelScope.launch(coroutineExceptionHandler) {
            try {
                withContext(Dispatchers.IO) {
                    val statuses = mutableListOf<Boolean>()
                    val workouts = workoutStore.workouts.filter { it.enabled && it.isActive }

                    if (workouts.isEmpty()) return@withContext

                    workouts.forEach {
                        try {
                            val workoutHistory = workoutHistoryDao.getLatestWorkoutHistoryByWorkoutId(it.id)
                                ?: return@forEach
                            val setHistories =
                                setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)
                            val exercises = it.workoutComponents.filterIsInstance<Exercise>() + it.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }
                            val exerciseInfos = exercises.mapNotNull { exercise ->
                                exerciseInfoDao.getExerciseInfoById(exercise.id)
                            }

                            val workoutRecord = workoutRecordDao.getWorkoutRecordByWorkoutId(it.id)
                            val exerciseSessionProgressions = exerciseSessionProgressionDao.getByWorkoutHistoryId(workoutHistory.id)

                            val errorLogs = try {
                                (context.applicationContext as? MyApplication)?.getErrorLogs() ?: emptyList()
                            } catch (e: Exception) {
                                Log.e("AppViewModel", "Error getting error logs", e)
                                emptyList()
                            }

                            val result = sendWorkoutHistoryStore(
                                dataClient!!,
                                WorkoutHistoryStore(
                                    WorkoutHistory = workoutHistory,
                                    SetHistories = setHistories,
                                    ExerciseInfos = exerciseInfos,
                                    WorkoutRecord = workoutRecord,
                                    ExerciseSessionProgressions = exerciseSessionProgressions,
                                    ErrorLogs = errorLogs
                                )
                            )
                            
                            // Clear error logs after successful send
                            if (result && errorLogs.isNotEmpty()) {
                                try {
                                    (context.applicationContext as? MyApplication)?.clearErrorLogs()
                                } catch (e: Exception) {
                                    Log.e("AppViewModel", "Error clearing error logs", e)
                                }
                            }
                            
                            statuses.add(result)
                        } catch (e: Exception) {
                            Log.e("AppViewModel", "Error sending workout data for ${it.id}", e)
                            statuses.add(false)
                        }
                    }

                    if (statuses.contains(false)) {
                        withContext(Dispatchers.Main) {
                            Toast.makeText(context, "Failed to send data to phone", Toast.LENGTH_SHORT)
                                .show()
                        }
                    } else {
                        withContext(Dispatchers.Main) {
                            Toast.makeText(context, "Data sent to phone", Toast.LENGTH_SHORT).show()
                        }
                    }
                }
            } catch (e: Exception) {
                Log.e("AppViewModel", "Error in sendAll", e)
                withContext(Dispatchers.Main) {
                    Toast.makeText(context, "Failed to send data to phone", Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    fun sendWorkoutHistoryToPhone(onEnd: (Boolean) -> Unit = {}) {
        viewModelScope.launch(coroutineExceptionHandler + Dispatchers.IO) {
            try {
                val workoutHistory =
                    workoutHistoryDao.getLatestWorkoutHistoryByWorkoutId(selectedWorkout.value.id)

                if (workoutHistory == null) {
                    withContext(Dispatchers.Main) {
                        onEnd(false)
                    }
                    return@launch
                }

                val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)
                val workoutRecord = workoutRecordDao.getWorkoutRecordByWorkoutId(selectedWorkout.value.id)

                val exerciseInfos =
                    selectedWorkout.value.workoutComponents.filterIsInstance<Exercise>().mapNotNull {
                        exerciseInfoDao.getExerciseInfoById(it.id)
                    } + selectedWorkout.value.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }.mapNotNull {
                        exerciseInfoDao.getExerciseInfoById(it.id)
                    }

                val exerciseSessionProgressions = exerciseSessionProgressionDao.getByWorkoutHistoryId(workoutHistory.id)

                // Note: Error logs will be included in pushAndStoreWorkoutData instead
                // since we don't have context here
                val result = dataClient?.let {
                    sendWorkoutHistoryStore(
                        it, WorkoutHistoryStore(
                            WorkoutHistory = workoutHistory,
                            SetHistories = setHistories,
                            ExerciseInfos = exerciseInfos,
                            WorkoutRecord = workoutRecord,
                            ExerciseSessionProgressions = exerciseSessionProgressions
                        )
                    )
                } ?: false

                withContext(Dispatchers.Main) {
                    onEnd(result)
                }
            } catch (e: Exception) {
                Log.e("AppViewModel", "Error sending workout history to phone", e)
                withContext(Dispatchers.Main) {
                    onEnd(false)
                }
            }
        }
    }

    override fun startWorkout() {

        _headerDisplayMode.value = 0
        _hrDisplayMode.value = 0
        super.startWorkout()
    }

    override fun goToNextState() {
        super.goToNextState()
        reEvaluateDimmingForCurrentState()
    }

    override fun resumeWorkoutFromRecord(onEnd: suspend () -> Unit) {

        _headerDisplayMode.value = 0
        _hrDisplayMode.value = 0

        super.resumeWorkoutFromRecord {
            lightScreenUp()
            onEnd()
        }
    }

    override fun pushAndStoreWorkoutData(
        isDone: Boolean,
        context: Context?,
        forceNotSend: Boolean,
        onEnd: suspend () -> Unit
    ) {
        super.pushAndStoreWorkoutData(isDone, context, forceNotSend) {
            if (!forceNotSend) {
                val currentState = workoutState.value
                val shouldSendData = (currentState != setStates.lastOrNull() || isDone)

                if(currentState is WorkoutState.Set){
                    upsertWorkoutRecord(currentState.exerciseId,currentState.setIndex)
                }

                if (shouldSendData && dataClient != null) {
                    try {
                        val exerciseInfos = mutableListOf<ExerciseInfo>()
                        val exercises = selectedWorkout.value.workoutComponents.filterIsInstance<Exercise>() +
                                selectedWorkout.value.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }

                        exercises.forEach { exercise ->
                            exerciseInfoDao.getExerciseInfoById(exercise.id)?.let {
                                exerciseInfos.add(it)
                            }
                        }

                        val exerciseSessionProgressions = exerciseSessionProgressionDao.getByWorkoutHistoryId(currentWorkoutHistory!!.id)

                        val errorLogs = try {
                            (context?.applicationContext as? MyApplication)?.getErrorLogs() ?: emptyList()
                        } catch (e: Exception) {
                            Log.e("AppViewModel", "Error getting error logs", e)
                            emptyList()
                        }

                        val result = sendWorkoutHistoryStore(
                            dataClient!!,
                            WorkoutHistoryStore(
                                WorkoutHistory = currentWorkoutHistory!!,
                                SetHistories = executedSetsHistory,
                                ExerciseInfos = exerciseInfos,
                                WorkoutRecord = _workoutRecord,
                                ExerciseSessionProgressions = exerciseSessionProgressions,
                                ErrorLogs = errorLogs
                            )
                        )

                        // Clear error logs after successful send
                        if (result && errorLogs.isNotEmpty() && context != null) {
                            try {
                                (context.applicationContext as? MyApplication)?.clearErrorLogs()
                            } catch (e: Exception) {
                                Log.e("AppViewModel", "Error clearing error logs", e)
                            }
                        }

                        if (context != null && !result) {
                            withContext(Dispatchers.Main) {
                                Toast.makeText(context, "Failed to send data to phone", Toast.LENGTH_SHORT).show()
                            }
                        }
                    } catch (e: Exception) {
                        Log.e("AppViewModel", "Error in pushAndStoreWorkoutData", e)
                        if (context != null) {
                            withContext(Dispatchers.Main) {
                                Toast.makeText(context, "Failed to send data to phone", Toast.LENGTH_SHORT).show()
                            }
                        }
                    }
                }
            }
            onEnd()
        }
    }
}
