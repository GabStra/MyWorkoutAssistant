package com.gabstra.myworkoutassistant

import android.content.Intent
import android.util.Log
import android.widget.Toast
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.ErrorLog
import com.gabstra.myworkoutassistant.shared.ErrorLogDao
import com.gabstra.myworkoutassistant.shared.ExerciseInfoDao
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgressionDao
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
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.google.android.gms.tasks.Tasks
import com.google.android.gms.wearable.DataEventBuffer
import com.google.android.gms.wearable.DataMapItem
import com.google.android.gms.wearable.PutDataMapRequest
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
    private lateinit var exerciseSessionProgressionDao: ExerciseSessionProgressionDao
    private lateinit var errorLogDao: ErrorLogDao

    override fun onCreate() {
        super.onCreate()
        val db = AppDatabase.getDatabase(this)
        setHistoryDao = db.setHistoryDao()
        workoutHistoryDao = db.workoutHistoryDao()
        exerciseInfoDao = db.exerciseInfoDao()
        workoutRecordDao = db.workoutRecordDao()
        exerciseSessionProgressionDao = db.exerciseSessionProgressionDao()
        errorLogDao = db.errorLogDao()
    }

    override fun onDataChanged(dataEvents: DataEventBuffer) {
        val packageName = this.packageName
        try {
            // Collect events first to avoid multiple iterations
            val eventsList = mutableListOf<com.google.android.gms.wearable.DataEvent>()
            dataEvents.forEach { eventsList.add(it) }
            
            // Process sync handshake messages first
            eventsList.forEach { dataEvent ->
                val uri = dataEvent.dataItem.uri
                val eventType = dataEvent.type
                
                // Only process CHANGED events, ignore DELETED
                if (eventType != com.google.android.gms.wearable.DataEvent.TYPE_CHANGED) {
                    return@forEach
                }
                
                when (uri.path) {
                    SYNC_ACK_PATH -> {
                        val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                        val transactionId = dataMap.getString("transactionId")
                        if (transactionId != null) {
                            Log.d("DataLayerSync", "Received SYNC_ACK for transaction: $transactionId")
                            SyncHandshakeManager.completeAck(transactionId)
                        } else {
                            Log.w("DataLayerSync", "Received SYNC_ACK without transactionId")
                        }
                    }
                    SYNC_COMPLETE_PATH -> {
                        val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                        val transactionId = dataMap.getString("transactionId")
                        val timestamp = dataMap.getString("timestamp", "unknown")
                        if (transactionId != null) {
                            Log.d("DataLayerSync", "Received SYNC_COMPLETE for transaction: $transactionId, timestamp: $timestamp")
                            SyncHandshakeManager.completeCompletion(transactionId)
                            Log.d("DataLayerSync", "Completed completion waiter for transaction: $transactionId")
                            // Show success toast
                            scope.launch(Dispatchers.Main) {
                                Toast.makeText(
                                    this@DataLayerListenerService,
                                    "Sync completed successfully",
                                    Toast.LENGTH_SHORT
                                ).show()
                            }
                        } else {
                            Log.w("DataLayerSync", "Received SYNC_COMPLETE without transactionId, timestamp: $timestamp")
                        }
                    }
                }
            }
            
            // Process other data events
            eventsList.forEach { dataEvent ->
                val uri = dataEvent.dataItem.uri
                val eventType = dataEvent.type
                when (uri.path) {
                    SYNC_REQUEST_PATH -> {
                        val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                        val transactionId = dataMap.getString("transactionId")
                        
                        if (transactionId != null) {
                            Log.d("DataLayerSync", "Received SYNC_REQUEST for transaction: $transactionId")
                            scope.launch(Dispatchers.IO) {
                                try {
                                    // Send acknowledgment - create new DataMapRequest
                                    val ackRequest = PutDataMapRequest.create(SYNC_ACK_PATH).apply {
                                        dataMap.putString("transactionId", transactionId)
                                        dataMap.putString("timestamp", System.currentTimeMillis().toString())
                                    }.asPutDataRequest().setUrgent()
                                    
                                    dataClient.putDataItem(ackRequest)
                                    Log.d("DataLayerSync", "Sent sync acknowledgment for transaction: $transactionId")
                                } catch (exception: Exception) {
                                    Log.e("DataLayerSync", "Error sending sync acknowledgment for transaction: $transactionId", exception)
                                }
                            }
                        } else {
                            Log.w("DataLayerSync", "Received SYNC_REQUEST without transactionId")
                        }
                    }

                    WORKOUT_HISTORY_STORE_PATH -> {
                        // Only process CHANGED events, ignore DELETED
                        if (eventType != com.google.android.gms.wearable.DataEvent.TYPE_CHANGED) {
                            return@forEach
                        }
                        val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                        val compressedJson = dataMap.getByteArray("compressedJson")
                        val transactionId = dataMap.getString("transactionId")

                        // Use a standalone IO scope for long-running DB work so it isn't
                        // cancelled if the short-lived service instance is destroyed.
                        CoroutineScope(Dispatchers.IO).launch {
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
                                    exerciseSessionProgressionDao.insertAllWithVersionCheck(*workoutHistoryStore.ExerciseSessionProgressions.toTypedArray())
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

                                        val validSetHistories = setHistories
                                            .dropWhile { it.setData is RestSetData }
                                            .dropLastWhile { it.setData is RestSetData }
                                            .filter { it ->
                                                when(val setData = it.setData){
                                                    is BodyWeightSetData -> setData.subCategory != SetSubCategory.RestPauseSet
                                                    is WeightSetData -> setData.subCategory != SetSubCategory.RestPauseSet
                                                    is RestSetData -> setData.subCategory != SetSubCategory.RestPauseSet
                                                    else -> true
                                                }
                                            }

                                        for (setHistory in validSetHistories) {
                                            val newSet = getNewSetFromSetHistory(setHistory)
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
                                    val db = AppDatabase.getDatabase(this@DataLayerListenerService)
                                    saveWorkoutStoreToDownloads(this@DataLayerListenerService, updatedWorkoutStore, db)
                                }

                                // Save error logs if present
                                if (workoutHistoryStore.ErrorLogs.isNotEmpty()) {
                                    errorLogDao.insertAll(*workoutHistoryStore.ErrorLogs.toTypedArray())
                                }

                                val intent = Intent(INTENT_ID).apply {
                                    putExtra(UPDATE_WORKOUTS, UPDATE_WORKOUTS)
                                }

                                intent.apply { setPackage(packageName) }
                                sendBroadcast(intent)

                                // Send completion acknowledgment
                                transactionId?.let { tid ->
                                    try {
                                        Log.d("DataLayerSync", "Preparing to send SYNC_COMPLETE for transaction: $tid (workout history processed)")
                                        val completeDataMapRequest = PutDataMapRequest.create(SYNC_COMPLETE_PATH)
                                        completeDataMapRequest.dataMap.putString("transactionId", tid)
                                        val timestamp = System.currentTimeMillis().toString()
                                        completeDataMapRequest.dataMap.putString("timestamp", timestamp)
                                        
                                        val completeRequest = completeDataMapRequest.asPutDataRequest().setUrgent()
                                        Log.d("DataLayerSync", "Sending SYNC_COMPLETE for transaction: $tid, timestamp: $timestamp")
                                        val task = dataClient.putDataItem(completeRequest)
                                        Tasks.await(task)
                                        Log.d("DataLayerSync", "Successfully sent SYNC_COMPLETE for transaction: $tid (workout history)")
                                        // Note: Toast is shown on WearOS when it receives this completion message
                                    } catch (exception: Exception) {
                                        Log.e("DataLayerSync", "Failed to send SYNC_COMPLETE for transaction: $tid", exception)
                                    }
                                }

                            } catch (exception: Exception) {
                                Log.e("DataLayerSync", "Error processing workout history store", exception)
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

                    CLEAR_ERROR_LOGS_PATH -> {
                        scope.launch(Dispatchers.IO) {
                            try {
                                errorLogDao.deleteAll()
                                Log.d("DataLayerListenerService", "Error logs cleared from mobile")
                            } catch (e: Exception) {
                                Log.e("DataLayerListenerService", "Error clearing error logs", e)
                            }
                        }
                    }

                    ERROR_LOGS_SYNC_PATH -> {
                        val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                        val compressedJson = dataMap.getByteArray("compressedJson")

                        scope.launch(Dispatchers.IO) {
                            try {
                                val errorLogsJson = decompressToString(compressedJson!!)

                                val gson = GsonBuilder()
                                    .registerTypeAdapter(LocalDateTime::class.java, LocalDateTimeAdapter())
                                    .create()

                                val errorLogs = gson.fromJson(
                                    errorLogsJson,
                                    Array<ErrorLog>::class.java
                                ).toList()

                                if (errorLogs.isNotEmpty()) {
                                    errorLogDao.insertAll(*errorLogs.toTypedArray())
                                    Log.d("DataLayerListenerService", "Synced ${errorLogs.size} error logs from watch")
                                    
                                    // Send broadcast to show toast notification
                                    val intent = Intent(INTENT_ID).apply {
                                        putExtra(ERROR_LOGS_SYNCED, errorLogs.size.toString())
                                    }
                                    intent.apply { setPackage(packageName) }
                                    sendBroadcast(intent)
                                }
                            } catch (exception: Exception) {
                                Log.e("DataLayerListenerService", "Error processing error logs sync", exception)
                            }
                        }
                    }
                }
            }
        } catch (exception: Exception) {
            Log.e("DataLayerSync", "Error processing data events", exception)
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
        const val CLEAR_ERROR_LOGS_PATH = "/clearErrorLogs"
        const val ERROR_LOGS_SYNC_PATH = "/errorLogsSync"
        const val INTENT_ID = "com.gabstra.myworkoutassistant.WORKOUT_STORE"
        const val UPDATE_WORKOUTS = "update_workouts"
        const val ERROR_LOGS_SYNCED = "error_logs_synced"
        const val PAGE = "page"
        const val SYNC_REQUEST_PATH = "/syncRequest"
        const val SYNC_ACK_PATH = "/syncAck"
        const val SYNC_COMPLETE_PATH = "/syncComplete"
        const val HANDSHAKE_TIMEOUT_MS = 5000L
        const val COMPLETION_TIMEOUT_MS = 30000L
    }
}
