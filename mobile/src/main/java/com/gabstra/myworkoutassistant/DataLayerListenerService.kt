package com.gabstra.myworkoutassistant

import android.content.Intent
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.adapters.LocalDateAdapter
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryStore
import com.gabstra.myworkoutassistant.shared.adapters.SetDataAdapter
import com.gabstra.myworkoutassistant.shared.setdata.SetData
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
                WORKOUT_HISTORY_STORE_PATH -> {
                    val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                    val workoutHistoryStoreJson = dataMap.getString("json")

                    scope.launch {
                        try{
                            val db = AppDatabase.getDatabase(this@DataLayerListenerService)
                            val setHistoryDao = db.setHistoryDao()
                            val workoutHistoryDao= db.workoutHistoryDao()

                            val gson = GsonBuilder()
                                .registerTypeAdapter(LocalDate::class.java, LocalDateAdapter())
                                .registerTypeAdapter(SetData::class.java, SetDataAdapter())
                                .create()
                            val workoutHistoryStore = gson.fromJson(workoutHistoryStoreJson, WorkoutHistoryStore::class.java)

                            val existingWorkouts = workoutHistoryDao.getWorkoutsByWorkoutIdAndDate(workoutHistoryStore.WorkoutHistory.workoutId,workoutHistoryStore.WorkoutHistory.date)

                            if(existingWorkouts.isNotEmpty()){
                                for(workout in existingWorkouts){
                                    workoutHistoryDao.deleteById(workout.id)
                                }
                            }

                            workoutHistoryDao.insert(workoutHistoryStore.WorkoutHistory)
                            setHistoryDao.insertAll(*workoutHistoryStore.ExerciseHistories.toTypedArray())
                        }catch (exception: Exception) {
                            exception.printStackTrace()
                        }
                    }
                }
                OPEN_PAGE_PATH -> {
                    val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                    val valueToPass = dataMap.getString("page") // Replace "key" with your actual key

                    // Start an activity and pass the extracted value
                    val intent = Intent(this, MainActivity::class.java).apply {
                        putExtra("page", valueToPass) // Replace "extra_key" with your actual extra key
                        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) // Required for starting an activity from a service
                        addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP) // This flag helps to reuse the existing instance
                    }
                    startActivity(intent)
                }
            }
        }

        super.onDataChanged(dataEvents)
    }

    override fun onDestroy() {
        super.onDestroy()
        scope.cancel()
    }

    companion object {
        private const val WORKOUT_HISTORY_STORE_PATH = "/workoutHistoryStore"
        private const val OPEN_PAGE_PATH = "/openPagePath" // Define your new URI path here
    }
}