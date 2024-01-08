package com.gabstra.myworkoutassistant

import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.adapters.LocalDateAdapter
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryStore
import com.google.android.gms.wearable.DataEventBuffer
import com.google.android.gms.wearable.DataMapItem
import com.google.android.gms.wearable.WearableListenerService
import com.google.gson.GsonBuilder
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import java.time.LocalDate

class DataLayerListenerService : WearableListenerService() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onDataChanged(dataEvents: DataEventBuffer) {
        dataEvents.forEach { dataEvent ->
            val uri = dataEvent.dataItem.uri
            when (uri.path) {
                "/workoutHistoryStore" -> {
                    val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                    val workoutHistoryStoreJson = dataMap.getString("json")

                    scope.launch {
                        try{
                            val db = AppDatabase.getDatabase(this@DataLayerListenerService)
                            val exerciseHistoryDao= db.setHistoryDao()
                            val workoutHistoryDao= db.workoutHistoryDao()

                            val gson = GsonBuilder()
                                .registerTypeAdapter(LocalDate::class.java, LocalDateAdapter())
                                .create()
                            val workoutHistoryStore = gson.fromJson(workoutHistoryStoreJson, WorkoutHistoryStore::class.java)
                            //Log.d("WORKOUT_HISTORY","RECEIVED: ${workoutHistoryStoreJson}")

                            val existingWorkouts = workoutHistoryDao.getWorkoutsByWorkoutIdAndDate(workoutHistoryStore.WorkoutHistory.workoutId,workoutHistoryStore.WorkoutHistory.date)

                            if(existingWorkouts.isNotEmpty()){
                                for(workout in existingWorkouts){
                                    workoutHistoryDao.deleteById(workout.id)
                                }
                            }

                            val workoutHistoryId = workoutHistoryDao.insert(workoutHistoryStore.WorkoutHistory ).toInt()
                            val executedExercisesHistory = workoutHistoryStore.ExerciseHistories.map {
                                it.copy(workoutHistoryId = workoutHistoryId)
                            }
                            exerciseHistoryDao.insertAll(*executedExercisesHistory.toTypedArray())
                        }catch (exception: Exception) {
                            exception.printStackTrace()
                        }
                    }
                }
            }
        }

        super.onDataChanged(dataEvents)
    }

    override fun onDestroy() {
        super.onDestroy()
        scope.cancel()
    }
}