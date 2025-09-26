package com.gabstra.myworkoutassistant

import android.content.Intent
import android.util.Log
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.ExerciseInfoDao
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryStore
import com.gabstra.myworkoutassistant.shared.WorkoutManager.Companion.addSetToExerciseRecursively
import com.gabstra.myworkoutassistant.shared.WorkoutManager.Companion.removeSetsFromExerciseRecursively
import com.gabstra.myworkoutassistant.shared.WorkoutManager.Companion.updateWorkoutOld
import com.gabstra.myworkoutassistant.shared.WorkoutRecordDao
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.adapters.LocalDateAdapter
import com.gabstra.myworkoutassistant.shared.adapters.LocalDateTimeAdapter
import com.gabstra.myworkoutassistant.shared.adapters.LocalTimeAdapter
import com.gabstra.myworkoutassistant.shared.adapters.SetDataAdapter
import com.gabstra.myworkoutassistant.shared.decompressToString
import com.gabstra.myworkoutassistant.shared.getNewSetFromSetHistory
import com.gabstra.myworkoutassistant.shared.removeRestAndRestPause
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.google.android.gms.wearable.DataEventBuffer
import com.google.android.gms.wearable.DataMapItem
import com.google.android.gms.wearable.Wearable
import com.google.android.gms.wearable.WearableListenerService
import com.google.gson.GsonBuilder
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime

class DataLayerListenerService : WearableListenerService() {
    private val dataClient by lazy { Wearable.getDataClient(this) }

    private val workoutStoreRepository by lazy { WorkoutStoreRepository(this.filesDir) }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private lateinit var workoutHistoryDao: WorkoutHistoryDao
    private lateinit var setHistoryDao: SetHistoryDao
    private lateinit var exerciseInfoDao: ExerciseInfoDao
    private lateinit var workoutRecordDao: WorkoutRecordDao

    override fun onCreate() {
        super.onCreate()
        val db = AppDatabase.getDatabase(this)
        setHistoryDao = db.setHistoryDao()
        workoutHistoryDao = db.workoutHistoryDao()
        exerciseInfoDao = db.exerciseInfoDao()
        workoutRecordDao = db.workoutRecordDao()
    }

    override fun onDataChanged(dataEvents: DataEventBuffer) {
        val packageName = this.packageName
        try {
            dataEvents.forEach { dataEvent ->
                val uri = dataEvent.dataItem.uri
                when (uri.path) {
                    WORKOUT_HISTORY_STORE_PATH -> {
                        val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                        val compressedJson = dataMap.getByteArray("compressedJson")

                        scope.launch(Dispatchers.IO) {
                            try {
                                val workoutHistoryStoreJson = decompressToString(compressedJson!!)

                                val gson = GsonBuilder()
                                    .registerTypeAdapter(LocalDate::class.java, LocalDateAdapter())
                                    .registerTypeAdapter(LocalTime::class.java, LocalTimeAdapter())
                                    .registerTypeAdapter(LocalDateTime::class.java,LocalDateTimeAdapter())
                                    .registerTypeAdapter(SetData::class.java, SetDataAdapter())
                                    .create()

                                val workoutHistoryStore = gson.fromJson(
                                    workoutHistoryStoreJson,
                                    WorkoutHistoryStore::class.java
                                )

                                val workoutStore = workoutStoreRepository.getWorkoutStore()
                                val workout = workoutStore.workouts.find { it.id == workoutHistoryStore.WorkoutHistory.workoutId }

                                if(workout == null) {
                                    return@launch
                                }

                                workoutHistoryDao.insertWithVersionCheck(workoutHistoryStore.WorkoutHistory)
                                setHistoryDao.insertAllWithVersionCheck(*workoutHistoryStore.SetHistories.toTypedArray())

                                if(workoutHistoryStore.WorkoutRecord != null){
                                    workoutRecordDao.deleteByWorkoutId(workout.id)
                                    workoutRecordDao.insert(workoutHistoryStore.WorkoutRecord!!)
                                }

                                if (workoutHistoryStore.WorkoutHistory.isDone) {
                                    exerciseInfoDao.insertAllWithVersionCheck(*workoutHistoryStore.ExerciseInfos.toTypedArray())
                                    workoutRecordDao.deleteByWorkoutId(workout.id)

                                    val setHistoriesByExerciseId = workoutHistoryStore.SetHistories
                                        .filter { it.exerciseId != null }
                                        .groupBy { it.exerciseId }

                                    val exercises = workout.workoutComponents.filterIsInstance<Exercise>() + workout.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }
                                    var workoutComponents = workout.workoutComponents

                                    for (exercise in exercises) {
                                        if(exercise.doNotStoreHistory) continue
                                        val setHistories = setHistoriesByExerciseId[exercise.id]?.sortedBy { it.order } ?: continue

                                        workoutComponents = removeSetsFromExerciseRecursively(workoutComponents,exercise)

                                        val newSets = setHistories.map { getNewSetFromSetHistory(it) }

                                        val setsToAdd = removeRestAndRestPause(
                                            sets = newSets,
                                            isRestPause = {
                                                when (it) {
                                                    is BodyWeightSet -> it.isRestPause
                                                    is WeightSet -> it.isRestPause
                                                    else -> false
                                                }
                                            },
                                            isRestSet = { it is RestSet } // adapt if your rest set type differs
                                        )

                                        for (setHistory in setHistories) {
                                            val newSet = getNewSetFromSetHistory(setHistory)
                                            if(newSet !in setsToAdd) continue
                                            workoutComponents = addSetToExerciseRecursively(workoutComponents,exercise,newSet,setHistory.order)
                                        }
                                    }

                                    val newWorkout = workout.copy(workoutComponents = workoutComponents)
                                    val updatedWorkoutStore = workoutStore.copy(
                                        workouts = updateWorkoutOld(
                                            workoutStore.workouts,
                                            workout,
                                            newWorkout
                                        )
                                    )
                                    workoutStoreRepository.saveWorkoutStore(updatedWorkoutStore)
                                }

                                val intent = Intent(INTENT_ID).apply {
                                    putExtra(UPDATE_WORKOUTS, UPDATE_WORKOUTS)
                                }

                                intent.apply { setPackage(packageName) }
                                sendBroadcast(intent)

                            } catch (exception: Exception) {
                                Log.e("DataLayerListenerService", "Error processing workout history store", exception)
                            }
                        }
                    }

                    OPEN_PAGE_PATH -> {
                        val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                        val valueToPass =
                            dataMap.getString(PAGE) // Replace "key" with your actual key
                        val context = this
                        scope.launch(Dispatchers.IO) {
                            // Start an activity and pass the extracted value
                            val intent = Intent(context, MainActivity::class.java).apply {
                                putExtra(
                                    PAGE,
                                    valueToPass
                                ) // Replace "extra_key" with your actual extra key
                                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) // Required for starting an activity from a service
                                addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP) // This flag helps to reuse the existing instance
                            }
                            startActivity(intent)
                        }
                    }
                }
            }
        } catch (exception: Exception) {
            Log.e("DataLayerListenerService", "Error processing data events", exception)
        } finally {
            super.onDataChanged(dataEvents)
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        scope.cancel()
    }

    companion object {
        private const val WORKOUT_HISTORY_STORE_PATH = "/workoutHistoryStore"
        private const val OPEN_PAGE_PATH = "/openPagePath" // Define your new URI path here
        const val INTENT_ID = "com.gabstra.myworkoutassistant.WORKOUT_STORE"
        const val UPDATE_WORKOUTS = "update_workouts"
        const val PAGE = "page"
    }
}