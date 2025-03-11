package com.gabstra.myworkoutassistant.data

import android.content.Context
import android.util.Log
import android.widget.Toast
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue

import androidx.lifecycle.viewModelScope
import com.gabstra.myworkoutassistant.shared.ExerciseInfo
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryStore
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.Node
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.UUID

class AppViewModel : WorkoutViewModel() {
    private var dataClient: DataClient? = null
    var phoneNode by mutableStateOf<Node?>(null)

    val isPhoneConnectedAndHasApp: Boolean
        get() = phoneNode != null


    fun initDataClient(client: DataClient) {
        dataClient = client
    }


    fun sendAll(context: Context) {
        viewModelScope.launch {
            withContext(Dispatchers.IO) {
                val statuses = mutableListOf<Boolean>()
                val workouts = workoutStore.workouts.filter { it.enabled && it.isActive }

                if (workouts.isEmpty()) return@withContext

                workouts.forEach {
                    val workoutHistory = workoutHistoryDao.getLatestWorkoutHistoryByWorkoutId(it.id)
                        ?: return@forEach
                    val setHistories =
                        setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)
                    val exercises = it.workoutComponents.filterIsInstance<Exercise>() + it.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }
                    val exerciseInfos = exercises.mapNotNull { exercise ->
                        exerciseInfoDao.getExerciseInfoById(exercise.id)
                    }

                    val result = sendWorkoutHistoryStore(
                        dataClient!!,
                        WorkoutHistoryStore(
                            WorkoutHistory = workoutHistory,
                            SetHistories = setHistories,
                            ExerciseInfos = exerciseInfos
                        )
                    )
                    statuses.add(result)
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
        }
    }

    fun sendWorkoutHistoryToPhone(onEnd: (Boolean) -> Unit = {}) {
        viewModelScope.launch(Dispatchers.IO) {
            val workoutHistory =
                workoutHistoryDao.getLatestWorkoutHistoryByWorkoutId(selectedWorkout.value.id)
            if (workoutHistory == null) {
                withContext(Dispatchers.Main) {
                    onEnd(false)
                }
                return@launch
            }

            val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)

            val exerciseInfos =
                selectedWorkout.value.workoutComponents.filterIsInstance<Exercise>().mapNotNull {
                    exerciseInfoDao.getExerciseInfoById(it.id)
                } + selectedWorkout.value.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }.mapNotNull {
                    exerciseInfoDao.getExerciseInfoById(it.id)
                }

            dataClient?.let {
                sendWorkoutHistoryStore(
                    it, WorkoutHistoryStore(
                        WorkoutHistory = workoutHistory,
                        SetHistories = setHistories,
                        ExerciseInfos = exerciseInfos
                    )
                )
            }

            withContext(Dispatchers.Main) {
                onEnd(true)
            }
        }
    }

    // Method to send workout history store to the phone
    private fun sendWorkoutHistoryStore(
        dataClient: DataClient,
        workoutHistoryStore: WorkoutHistoryStore
    ): Boolean {
        // Implementation for sending data to the phone
        // This would use the Wearable DataClient to send data
        return true // Placeholder return
    }

    override fun pushAndStoreWorkoutData(
        isDone: Boolean,
        context: Context?,
        forceNotSend: Boolean,
        onEnd: () -> Unit
    ) {
        super.pushAndStoreWorkoutData(isDone, context, forceNotSend) {
            // After storing the data, send it to the phone if needed
            if (!forceNotSend) {
                val currentState = workoutState.value
                val shouldSendData = (currentState != setStates.lastOrNull() || isDone) && !forceNotSend

                if (shouldSendData && dataClient != null) {
                    val exerciseInfos = mutableListOf<ExerciseInfo>()
                    // Get exercise infos for sending
                    val exercises = selectedWorkout.value.workoutComponents.filterIsInstance<Exercise>() +
                        selectedWorkout.value.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }

                    viewModelScope.launch(Dispatchers.IO) {
                        exercises.forEach { exercise ->
                            exerciseInfoDao.getExerciseInfoById(exercise.id)?.let {
                                exerciseInfos.add(it)
                            }
                        }
                    }

                    val result = sendWorkoutHistoryStore(
                        dataClient!!,
                        WorkoutHistoryStore(
                            WorkoutHistory = currentWorkoutHistory!!,
                            SetHistories = executedSetsHistory,
                            ExerciseInfos = exerciseInfos
                        )
                    )

                    if (context != null && !result) {
                        Toast.makeText(context, "Failed to send data to phone", Toast.LENGTH_SHORT).show()
                    }
                }
            }
            onEnd()
        }
    }
}
