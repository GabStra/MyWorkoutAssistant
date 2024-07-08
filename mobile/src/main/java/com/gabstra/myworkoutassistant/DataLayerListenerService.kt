package com.gabstra.myworkoutassistant

import android.content.Intent
import com.gabstra.myworkoutassistant.shared.WorkoutManager.Companion.updateSetInExerciseRecursively
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.adapters.LocalDateAdapter
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryStore
import com.gabstra.myworkoutassistant.shared.WorkoutManager
import com.gabstra.myworkoutassistant.shared.WorkoutManager.Companion.updateWorkoutOld
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.adapters.LocalTimeAdapter
import com.gabstra.myworkoutassistant.shared.adapters.SetDataAdapter
import com.gabstra.myworkoutassistant.shared.decompressToString
import com.gabstra.myworkoutassistant.shared.getNewSetFromSetData
import com.gabstra.myworkoutassistant.shared.isSetDataValid
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
import java.time.LocalTime

class DataLayerListenerService : WearableListenerService() {
    private val workoutStoreRepository by lazy { WorkoutStoreRepository(this.filesDir) }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onDataChanged(dataEvents: DataEventBuffer) {
        dataEvents.forEach { dataEvent ->
            val uri = dataEvent.dataItem.uri
            when (uri.path) {
                WORKOUT_HISTORY_STORE_PATH -> {
                    val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                    val compressedJson = dataMap.getByteArray("compressedJson")
                    val workoutHistoryStoreJson = decompressToString(compressedJson!!)

                    scope.launch(Dispatchers.IO) {
                        try{
                            val db = AppDatabase.getDatabase(this@DataLayerListenerService)
                            val setHistoryDao = db.setHistoryDao()
                            val workoutHistoryDao = db.workoutHistoryDao()

                            val gson = GsonBuilder()
                                .registerTypeAdapter(LocalDate::class.java, LocalDateAdapter())
                                .registerTypeAdapter(LocalTime::class.java, LocalTimeAdapter())
                                .registerTypeAdapter(SetData::class.java, SetDataAdapter())
                                .create()
                            val workoutHistoryStore = gson.fromJson(workoutHistoryStoreJson, WorkoutHistoryStore::class.java)

                            val workoutHistory = workoutHistoryStore.WorkoutHistory

                            workoutHistoryDao.insert(workoutHistoryStore.WorkoutHistory)

                            setHistoryDao.insertAll(*workoutHistoryStore.ExerciseHistories.toTypedArray())
                            val setHistoriesByExerciseId = workoutHistoryStore.ExerciseHistories.groupBy { it.exerciseId }

                            val workoutStore = workoutStoreRepository.getWorkoutStore()
                            val workout = workoutStore.workouts.find { it.id == workoutHistoryStore.WorkoutHistory.workoutId }
                            if(workout != null){
                                val exercises = WorkoutManager.getAllExercisesFromWorkout(workout)
                                var workoutComponents = workout.workoutComponents

                                for (exercise in exercises){
                                    val setById = exercise.sets.associateBy { it.id }
                                    val setHistories = setHistoriesByExerciseId[exercise.id] ?: continue

                                    for(setHistory in setHistories){
                                        val isExistingSet = setById.containsKey(setHistory.setId)

                                        workoutComponents =
                                            if(isExistingSet) {
                                                val set = setById[setHistory.setId] ?: continue
                                                if(!isSetDataValid(set,setHistory.setData)) continue
                                                val newSet = getNewSetFromSetData(set,setHistory.setData) ?: continue
                                                updateSetInExerciseRecursively(workoutComponents,exercise,set,newSet)
                                            }else{
                                                val previousSet = exercise.sets[setHistory.order - 1]
                                                val newSet = getNewSetFromSetData(previousSet,setHistory.setData) ?: continue
                                                WorkoutManager.addSetToExerciseRecursively(workoutComponents,exercise,newSet,setHistory.order)
                                            }
                                    }
                                }

                                val newWorkout = workout.copy(workoutComponents = workoutComponents)
                                val updatedWorkoutStore = workoutStore.copy(workouts = updateWorkoutOld(workoutStore.workouts, workout, newWorkout))
                                workoutStoreRepository.saveWorkoutStore(updatedWorkoutStore)

                                val intent = Intent(INTENT_ID).apply {
                                    putExtra(UPDATE_WORKOUTS, UPDATE_WORKOUTS)
                                }
                                sendBroadcast(intent)
                            }

                        }catch (exception: Exception) {
                            exception.printStackTrace()
                        }
                    }
                }
                OPEN_PAGE_PATH -> {
                    val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                    val valueToPass = dataMap.getString(PAGE) // Replace "key" with your actual key

                    // Start an activity and pass the extracted value
                    val intent = Intent(this, MainActivity::class.java).apply {
                        putExtra(PAGE, valueToPass) // Replace "extra_key" with your actual extra key
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
        const val INTENT_ID = "com.gabstra.myworkoutassistant.workoutstore"
        const val UPDATE_WORKOUTS = "update_workouts"
        const val PAGE = "page"
    }
}