package com.gabstra.myworkoutassistant

import android.content.Context
import android.content.Intent
import android.util.Log
import android.widget.Toast
import androidx.core.content.edit
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
import com.gabstra.myworkoutassistant.shared.datalayer.DataLayerPaths
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
import com.google.gson.Gson
import com.google.gson.GsonBuilder
import com.google.gson.reflect.TypeToken
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import kotlin.io.encoding.Base64
import kotlin.io.encoding.ExperimentalEncodingApi

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

    private val sharedPreferences by lazy {
        getSharedPreferences(
            "workout_history_sync_state",
            Context.MODE_PRIVATE
        )
    }
    private val gson = Gson()
    private val workoutHistoryGson = GsonBuilder()
        .registerTypeAdapter(LocalDate::class.java, LocalDateAdapter())
        .registerTypeAdapter(LocalTime::class.java, LocalTimeAdapter())
        .registerTypeAdapter(LocalDateTime::class.java, LocalDateTimeAdapter())
        .registerTypeAdapter(SetData::class.java, SetDataAdapter())
        .create()

    @OptIn(ExperimentalEncodingApi::class)
    private var workoutHistoryChunks: MutableMap<Int, ByteArray>
        get() {
            val jsonString = sharedPreferences.getString("workout_history_chunks", null)
            if (jsonString.isNullOrEmpty()) {
                return mutableMapOf()
            }
            return try {
                val typeToken = object : TypeToken<Map<String, String>>() {}.type
                val base64Map: Map<String, String> = gson.fromJson(jsonString, typeToken)
                base64Map.mapNotNull { (indexStr, base64String) ->
                    try {
                        val index = indexStr.toInt()
                        val chunkData = Base64.decode(base64String)
                        Pair(index, chunkData)
                    } catch (e: Exception) {
                        Log.e(
                            "DataLayerListenerService",
                            "Failed to decode chunk at index $indexStr: ${e.message}"
                        )
                        null
                    }
                }.toMap().toMutableMap()
            } catch (e: Exception) {
                Log.e(
                    "DataLayerListenerService",
                    "Failed to parse workoutHistoryChunks from SharedPreferences with Gson: ${e.message}",
                    e
                )
                sharedPreferences.edit { remove("workout_history_chunks") }
                mutableMapOf()
            }
        }
        set(value) {
            if (value.isEmpty()) {
                sharedPreferences.edit { remove("workout_history_chunks") }
            } else {
                try {
                    val base64Map =
                        value.mapKeys { it.key.toString() }.mapValues { (_, byteArray) ->
                            Base64.encode(byteArray)
                        }
                    val jsonString = gson.toJson(base64Map)
                    sharedPreferences.edit { putString("workout_history_chunks", jsonString) }
                } catch (e: Exception) {
                    Log.e(
                        "DataLayerListenerService",
                        "Failed to save workoutHistoryChunks to SharedPreferences with Gson: ${e.message}",
                        e
                    )
                }
            }
        }

    private var expectedChunks: Int
        get() = sharedPreferences.getInt("expected_workout_history_chunks", 0)
        set(value) {
            sharedPreferences.edit() { putInt("expected_workout_history_chunks", value) }
        }

    private var ignoreUntilStartOrEnd: Boolean
        get() = sharedPreferences.getBoolean("ignore_workout_history_until_start_or_end", false)
        set(value) {
            sharedPreferences.edit() {
                putBoolean(
                    "ignore_workout_history_until_start_or_end",
                    value
                )
            }
        }

    private var hasStartedSync: Boolean
        get() = sharedPreferences.getBoolean("has_started_workout_history_sync", false)
        set(value) {
            sharedPreferences.edit() { putBoolean("has_started_workout_history_sync", value) }
        }

    private var currentTransactionId: String?
        get() = sharedPreferences.getString("current_workout_history_transaction_id", null)
        set(value) {
            if (value == null) {
                sharedPreferences.edit() { remove("current_workout_history_transaction_id") }
            } else {
                sharedPreferences.edit() {
                    putString(
                        "current_workout_history_transaction_id",
                        value
                    )
                }
            }
        }

    private var receivedChunkIndices: MutableSet<Int>
        get() {
            val indicesString =
                sharedPreferences.getString("received_workout_history_chunk_indices", null)
            if (indicesString.isNullOrEmpty()) {
                return mutableSetOf()
            }
            return try {
                val typeToken = object : TypeToken<List<Int>>() {}.type
                val indices: List<Int> = gson.fromJson(indicesString, typeToken)
                indices.toMutableSet()
            } catch (e: Exception) {
                Log.e(
                    "DataLayerListenerService",
                    "Failed to parse receivedChunkIndices: ${e.message}",
                    e
                )
                sharedPreferences.edit { remove("received_workout_history_chunk_indices") }
                mutableSetOf()
            }
        }
        set(value) {
            if (value.isEmpty()) {
                sharedPreferences.edit { remove("received_workout_history_chunk_indices") }
            } else {
                try {
                    val jsonString = gson.toJson(value.toList())
                    sharedPreferences.edit {
                        putString(
                            "received_workout_history_chunk_indices",
                            jsonString
                        )
                    }
                } catch (e: Exception) {
                    Log.e(
                        "DataLayerListenerService",
                        "Failed to save receivedChunkIndices: ${e.message}",
                        e
                    )
                }
            }
        }

    private fun combineChunks(chunks: List<ByteArray>): ByteArray {
        val totalLength = chunks.sumOf { it.size }
        val combinedArray = ByteArray(totalLength)

        var currentPosition = 0
        for (chunk in chunks) {
            chunk.copyInto(combinedArray, currentPosition)
            currentPosition += chunk.size
        }

        return combinedArray
    }
    
    /**
     * Checks connection state and throws exception if disconnected.
     * Used during sync operations to fail fast on disconnection.
     */
    private suspend fun checkConnectionDuringSync(transactionId: String?): Boolean {
        return try {
            val nodeClient = Wearable.getNodeClient(this)
            val nodes = Tasks.await(nodeClient.connectedNodes, 2, java.util.concurrent.TimeUnit.SECONDS)
            val isConnected = nodes.isNotEmpty()
            
            if (!isConnected) {
                Log.e(
                    "DataLayerSync",
                    "Connection lost during sync for transaction: $transactionId - failing fast"
                )
            } else {
                Log.d(
                    "DataLayerSync",
                    "Connection verified during sync for transaction: $transactionId - ${nodes.size} node(s) connected"
                )
            }
            
            isConnected
        } catch (e: Exception) {
            Log.w("DataLayerSync", "Could not check connection state during sync: ${e.message}")
            // If we can't check, assume connection is still there (don't fail on check errors)
            true
        }
    }

    override fun onCreate() {
        super.onCreate()
        val db = AppDatabase.getDatabase(this)
        setHistoryDao = db.setHistoryDao()
        workoutHistoryDao = db.workoutHistoryDao()
        exerciseInfoDao = db.exerciseInfoDao()
        workoutRecordDao = db.workoutRecordDao()
        exerciseSessionProgressionDao = db.exerciseSessionProgressionDao()
        errorLogDao = db.errorLogDao()
        
        // Detect service restart and handle incomplete syncs
        detectAndHandleServiceRestart()
    }
    
    /**
     * Detects if the service was restarted during an active sync and handles incomplete syncs.
     * This prevents stale state from persisting across service restarts.
     */
    private fun detectAndHandleServiceRestart() {
        val lastServiceStartTime = sharedPreferences.getLong("last_service_start_time", 0L)
        val currentTime = System.currentTimeMillis()
        val serviceRestartThreshold = 5000L // 5 seconds - if last start was more than 5 seconds ago, likely a restart
        
        // Check if there's an incomplete sync
        val hasIncompleteSync = hasStartedSync && currentTransactionId != null
        
        if (hasIncompleteSync && (currentTime - lastServiceStartTime > serviceRestartThreshold)) {
            Log.w(
                "DataLayerSync",
                "Detected service restart during active sync. Transaction: $currentTransactionId. Cleaning up stale state."
            )
            
            // Clean up incomplete sync state
            workoutHistoryChunks = mutableMapOf()
            receivedChunkIndices = mutableSetOf()
            expectedChunks = 0
            hasStartedSync = false
            ignoreUntilStartOrEnd = false
            currentTransactionId = null
            
            // Notify UI that sync was interrupted
            val intent = Intent(INTENT_ID).apply {
                putExtra(UPDATE_WORKOUTS, UPDATE_WORKOUTS)
                setPackage(packageName)
            }
            sendBroadcast(intent)
        }
        
        // Update last service start time
        sharedPreferences.edit().putLong("last_service_start_time", currentTime).apply()
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

                val path = uri.path ?: return@forEach
                when {
                    DataLayerPaths.matchesPrefix(path, DataLayerPaths.SYNC_ACK_PREFIX) -> {
                        val transactionId =
                            DataLayerPaths.parseTransactionId(path, DataLayerPaths.SYNC_ACK_PREFIX)
                        val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                        val timestampStr = dataMap.getString("timestamp")

                        // Ignore ACKs without transactionId
                        if (transactionId == null) {
                            Log.w(
                                "DataLayerSync",
                                "Received SYNC_ACK without transactionId - ignoring stale message"
                            )
                            return@forEach
                        }

                        // Ignore stale ACKs (older than threshold, default 60 seconds)
                        if (timestampStr != null) {
                            try {
                                val timestamp = timestampStr.toLong()
                                val currentTime = System.currentTimeMillis()
                                val age = currentTime - timestamp
                                // Get stale ACK threshold from SharedPreferences, default 60 seconds
                                val staleAckThreshold = getSharedPreferences("sync_timeouts", Context.MODE_PRIVATE)
                                    .getLong("stale_ack_threshold_ms", 60000L)
                                if (age > staleAckThreshold) {
                                    Log.w(
                                        "DataLayerSync",
                                        "Received stale SYNC_ACK for transaction: $transactionId (age: ${age}ms, threshold: ${staleAckThreshold}ms) - ignoring"
                                    )
                                    return@forEach
                                }
                            } catch (e: NumberFormatException) {
                                Log.w(
                                    "DataLayerSync",
                                    "Received SYNC_ACK with invalid timestamp format for transaction: $transactionId"
                                )
                            }
                        }

                        Log.d("DataLayerSync", "Received SYNC_ACK for transaction: $transactionId")
                        SyncHandshakeManager.completeAck(transactionId)
                    }

                    DataLayerPaths.matchesPrefix(path, DataLayerPaths.SYNC_COMPLETE_PREFIX) -> {
                        val transactionId = DataLayerPaths.parseTransactionId(
                            path,
                            DataLayerPaths.SYNC_COMPLETE_PREFIX
                        )
                        val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                        val timestamp = dataMap.getString("timestamp", "unknown")
                        transactionId?.let { tid ->
                            Log.d(
                                "DataLayerSync",
                                "Received SYNC_COMPLETE for transaction: $tid, timestamp: $timestamp"
                            )
                            SyncHandshakeManager.completeCompletion(tid)
                            Log.d(
                                "DataLayerSync",
                                "Completed completion waiter for transaction: $tid"
                            )
                            // Show success toast
                            scope.launch(Dispatchers.Main) {
                                Toast.makeText(
                                    this@DataLayerListenerService,
                                    "Sync completed successfully",
                                    Toast.LENGTH_SHORT
                                ).show()
                            }
                        } ?: run {
                            Log.w(
                                "DataLayerSync",
                                "Received SYNC_COMPLETE without transactionId, timestamp: $timestamp"
                            )
                        }
                    }

                    DataLayerPaths.matchesPrefix(path, DataLayerPaths.SYNC_ERROR_PREFIX) -> {
                        val transactionId = DataLayerPaths.parseTransactionId(
                            path,
                            DataLayerPaths.SYNC_ERROR_PREFIX
                        )
                        val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                        val errorMessage = dataMap.getString("errorMessage", "Unknown error")
                        transactionId?.let { tid ->
                            Log.e(
                                "DataLayerSync",
                                "Received SYNC_ERROR for transaction: $tid, error: $errorMessage"
                            )
                            SyncHandshakeManager.completeError(tid, errorMessage)
                        } ?: run {
                            Log.w(
                                "DataLayerSync",
                                "Received SYNC_ERROR without transactionId, error: $errorMessage"
                            )
                        }
                    }
                }
            }

            // Process other data events
            eventsList.forEach { dataEvent ->
                val uri = dataEvent.dataItem.uri
                val eventType = dataEvent.type
                val path = uri.path ?: return@forEach
                when {
                    DataLayerPaths.matchesPrefix(path, DataLayerPaths.SYNC_REQUEST_PREFIX) -> {
                        val transactionId = DataLayerPaths.parseTransactionId(
                            path,
                            DataLayerPaths.SYNC_REQUEST_PREFIX
                        )
                        val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                        // Also try to get from DataMap as fallback
                        val transactionIdFromMap = dataMap.getString("transactionId")
                        val finalTransactionId = transactionId ?: transactionIdFromMap

                        if (finalTransactionId != null) {
                            Log.d(
                                "DataLayerSync",
                                "Received SYNC_REQUEST for transaction: $finalTransactionId"
                            )
                            scope.launch(Dispatchers.IO) {
                                try {
                                    // Send acknowledgment to transaction-scoped path
                                    val ackPath = DataLayerPaths.buildPath(
                                        DataLayerPaths.SYNC_ACK_PREFIX,
                                        finalTransactionId
                                    )
                                    val ackRequest = PutDataMapRequest.create(ackPath).apply {
                                        dataMap.putString("transactionId", finalTransactionId)
                                        dataMap.putString(
                                            "timestamp",
                                            System.currentTimeMillis().toString()
                                        )
                                    }.asPutDataRequest().setUrgent()

                                    dataClient.putDataItem(ackRequest)
                                    Log.d(
                                        "DataLayerSync",
                                        "Sent sync acknowledgment for transaction: $finalTransactionId"
                                    )
                                } catch (exception: Exception) {
                                    Log.e(
                                        "DataLayerSync",
                                        "Error sending sync acknowledgment for transaction: $finalTransactionId",
                                        exception
                                    )
                                }
                            }
                        } else {
                            Log.w("DataLayerSync", "Received SYNC_REQUEST without transactionId")
                        }
                    }

                    path == WORKOUT_HISTORY_STORE_PATH -> {
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
                                    .registerTypeAdapter(
                                        LocalDateTime::class.java,
                                        LocalDateTimeAdapter()
                                    )
                                    .registerTypeAdapter(SetData::class.java, SetDataAdapter())
                                    .create()

                                val workoutHistoryStore = workoutHistoryGson.fromJson(
                                    workoutHistoryStoreJson,
                                    WorkoutHistoryStore::class.java
                                )

                                val workoutStore = workoutStoreRepository.getWorkoutStore()
                                val workout =
                                    workoutStore.workouts.find { it.id == workoutHistoryStore.WorkoutHistory.workoutId }

                                if (workout == null) {
                                    return@launch
                                }

                                workoutHistoryDao.insertWithVersionCheck(workoutHistoryStore.WorkoutHistory)
                                setHistoryDao.insertAllWithVersionCheck(*workoutHistoryStore.SetHistories.toTypedArray())

                                if (workoutHistoryStore.WorkoutRecord != null) {
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

                                    val exercises =
                                        workout.workoutComponents.filterIsInstance<Exercise>() + workout.workoutComponents.filterIsInstance<Superset>()
                                            .flatMap { it.exercises }
                                    var workoutComponents = workout.workoutComponents

                                    for (exercise in exercises) {
                                        if (exercise.doNotStoreHistory) continue
                                        val setHistories =
                                            setHistoriesByExerciseId[exercise.id]?.sortedBy { it.order }
                                                ?: continue

                                        workoutComponents = removeSetsFromExerciseRecursively(
                                            workoutComponents,
                                            exercise
                                        )

                                        val validSetHistories = setHistories
                                            .dropWhile { it.setData is RestSetData }
                                            .dropLastWhile { it.setData is RestSetData }
                                            .filter { it ->
                                                when (val setData = it.setData) {
                                                    is BodyWeightSetData -> setData.subCategory != SetSubCategory.RestPauseSet
                                                    is WeightSetData -> setData.subCategory != SetSubCategory.RestPauseSet
                                                    is RestSetData -> setData.subCategory != SetSubCategory.RestPauseSet
                                                    else -> true
                                                }
                                            }

                                        for (setHistory in validSetHistories) {
                                            val newSet = getNewSetFromSetHistory(setHistory)
                                            workoutComponents = addSetToExerciseRecursively(
                                                workoutComponents,
                                                exercise,
                                                newSet,
                                                setHistory.order
                                            )
                                        }
                                    }

                                    val newWorkout =
                                        workout.copy(workoutComponents = workoutComponents)
                                    val updatedWorkoutStore = workoutStore.copy(
                                        workouts = updateWorkoutOld(
                                            workoutStore.workouts,
                                            workout,
                                            newWorkout
                                        )
                                    )
                                    workoutStoreRepository.saveWorkoutStore(updatedWorkoutStore)
                                    val db = AppDatabase.getDatabase(this@DataLayerListenerService)
                                    saveWorkoutStoreToDownloads(
                                        this@DataLayerListenerService,
                                        updatedWorkoutStore,
                                        db
                                    )
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
                                        Log.d(
                                            "DataLayerSync",
                                            "Preparing to send SYNC_COMPLETE for transaction: $tid (workout history processed)"
                                        )
                                        val completePath = DataLayerPaths.buildPath(
                                            DataLayerPaths.SYNC_COMPLETE_PREFIX,
                                            tid
                                        )
                                        val completeDataMapRequest =
                                            PutDataMapRequest.create(completePath)
                                        completeDataMapRequest.dataMap.putString(
                                            "transactionId",
                                            tid
                                        )
                                        val timestamp = System.currentTimeMillis().toString()
                                        completeDataMapRequest.dataMap.putString(
                                            "timestamp",
                                            timestamp
                                        )

                                        val completeRequest =
                                            completeDataMapRequest.asPutDataRequest().setUrgent()
                                        Log.d(
                                            "DataLayerSync",
                                            "Sending SYNC_COMPLETE for transaction: $tid, timestamp: $timestamp"
                                        )
                                        val task = dataClient.putDataItem(completeRequest)
                                        Tasks.await(task)
                                        Log.d(
                                            "DataLayerSync",
                                            "Successfully sent SYNC_COMPLETE for transaction: $tid (workout history)"
                                        )
                                        // Note: Toast is shown on WearOS when it receives this completion message
                                    } catch (exception: Exception) {
                                        Log.e(
                                            "DataLayerSync",
                                            "Failed to send SYNC_COMPLETE for transaction: $tid",
                                            exception
                                        )
                                    }
                                }

                            } catch (exception: Exception) {
                                Log.e(
                                    "DataLayerSync",
                                    "Error processing workout history store",
                                    exception
                                )
                                exception.printStackTrace()

                                // Send error response back to sender
                                transactionId?.let { tid ->
                                    try {
                                        Log.e(
                                            "DataLayerSync",
                                            "Sending SYNC_ERROR for transaction: $tid due to processing error"
                                        )
                                        val errorMessage = exception.message
                                            ?: "Unknown error processing workout history store"
                                        val errorPath = DataLayerPaths.buildPath(
                                            DataLayerPaths.SYNC_ERROR_PREFIX,
                                            tid
                                        )
                                        val errorDataMapRequest =
                                            PutDataMapRequest.create(errorPath)
                                        errorDataMapRequest.dataMap.putString("transactionId", tid)
                                        errorDataMapRequest.dataMap.putString(
                                            "errorMessage",
                                            errorMessage
                                        )
                                        errorDataMapRequest.dataMap.putString(
                                            "timestamp",
                                            System.currentTimeMillis().toString()
                                        )

                                        val errorRequest =
                                            errorDataMapRequest.asPutDataRequest().setUrgent()
                                        val task = dataClient.putDataItem(errorRequest)
                                        Tasks.await(task)
                                        Log.e(
                                            "DataLayerSync",
                                            "Successfully sent SYNC_ERROR for transaction: $tid"
                                        )
                                    } catch (sendErrorException: Exception) {
                                        Log.e(
                                            "DataLayerSync",
                                            "Failed to send SYNC_ERROR for transaction: $tid",
                                            sendErrorException
                                        )
                                    }
                                }
                            }
                        }
                    }

                    // Handle transaction-scoped workout history paths
                    DataLayerPaths.matchesPrefix(
                        path,
                        DataLayerPaths.WORKOUT_HISTORY_START_PREFIX
                    ) ||
                            DataLayerPaths.matchesPrefix(
                                path,
                                DataLayerPaths.WORKOUT_HISTORY_CHUNK_PREFIX
                            ) -> {
                        val isStartPath = DataLayerPaths.matchesPrefix(
                            path,
                            DataLayerPaths.WORKOUT_HISTORY_START_PREFIX
                        )
                        val isChunkPath = DataLayerPaths.matchesPrefix(
                            path,
                            DataLayerPaths.WORKOUT_HISTORY_CHUNK_PREFIX
                        )

                        if (isStartPath || isChunkPath) {
                            val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap

                            // Parse transactionId from path
                            val transactionIdFromPath = if (isStartPath) {
                                DataLayerPaths.parseTransactionId(
                                    path,
                                    DataLayerPaths.WORKOUT_HISTORY_START_PREFIX
                                )
                            } else {
                                DataLayerPaths.parseTransactionId(
                                    path,
                                    DataLayerPaths.WORKOUT_HISTORY_CHUNK_PREFIX
                                )
                            }

                            // Parse chunkIndex from path (if chunk path)
                            val chunkIndexFromPath = if (isChunkPath) {
                                DataLayerPaths.parseChunkIndex(
                                    path,
                                    DataLayerPaths.WORKOUT_HISTORY_CHUNK_PREFIX
                                )
                            } else {
                                null
                            }

                            // Fallback to DataMap values if path parsing fails
                            val transactionId =
                                transactionIdFromPath ?: dataMap.getString("transactionId")
                            val chunkIndex = chunkIndexFromPath
                                ?: (if (dataMap.containsKey("chunkIndex")) dataMap.getInt(
                                    "chunkIndex",
                                    -1
                                ) else -1)

                            val isStart = isStartPath || dataMap.getBoolean("isStart", false)
                            val isLastChunk = dataMap.getBoolean("isLastChunk", false)
                            val workoutHistoryChunk = dataMap.getByteArray("chunk")
                            val isRetry = dataMap.getBoolean("isRetry", false)
                            val isLastRetryChunk = dataMap.getBoolean("isLastRetryChunk", false)

                            // Retry chunks with same transaction ID should not trigger shouldStop
                            val shouldStop = !isRetry && (
                                    (isStart && hasStartedSync) ||
                                            (workoutHistoryChunk != null && !hasStartedSync) ||
                                            (currentTransactionId != null && currentTransactionId != transactionId)
                                    )

                            Log.d(
                                "DataLayerListenerService",
                                "ignoreUntilStartOrEnd: $ignoreUntilStartOrEnd hasWorkoutHistoryChunk: ${workoutHistoryChunk != null} isStart: $isStart isLastChunk: $isLastChunk isRetry: $isRetry chunkIndex: $chunkIndex transactionId: $transactionId shouldStop: $shouldStop"
                            )

                            if (!ignoreUntilStartOrEnd && shouldStop && !isRetry) {
                                val intent = Intent(INTENT_ID).apply {
                                    putExtra(UPDATE_WORKOUTS, UPDATE_WORKOUTS)
                                    setPackage(packageName)
                                }

                                sendBroadcast(intent)

                                workoutHistoryChunks = mutableMapOf()
                                receivedChunkIndices = mutableSetOf()
                                expectedChunks = 0
                                hasStartedSync = false
                                currentTransactionId = null

                                ignoreUntilStartOrEnd = true
                                return@forEach
                            }

                            if (isStart) {
                                if (dataMap.containsKey("chunksCount")) {
                                    expectedChunks = dataMap.getInt("chunksCount", 0)
                                }

                                Log.d(
                                    "DataLayerSync",
                                    "Workout history backup started with expected chunks: $expectedChunks, transactionId: $transactionId"
                                )

                                workoutHistoryChunks = mutableMapOf()
                                receivedChunkIndices = mutableSetOf()
                                hasStartedSync = true
                                ignoreUntilStartOrEnd = false
                                currentTransactionId = transactionId
                            }

                            if (workoutHistoryChunk != null && (!ignoreUntilStartOrEnd || isRetry)) {
                                // Handle chunk with index
                                if (chunkIndex >= 0) {
                                    val currentChunks = workoutHistoryChunks.toMutableMap()
                                    currentChunks[chunkIndex] = workoutHistoryChunk
                                    workoutHistoryChunks = currentChunks

                                    val currentIndices = receivedChunkIndices.toMutableSet()
                                    currentIndices.add(chunkIndex)
                                    receivedChunkIndices = currentIndices

                                    Log.d(
                                        "DataLayerSync",
                                        "Received workout history chunk at index $chunkIndex. Total chunks: ${workoutHistoryChunks.size}, expected: $expectedChunks, isRetry: $isRetry"
                                    )
                                } else {
                                    // Fallback for backwards compatibility - should not happen with new implementation
                                    Log.w(
                                        "DataLayerSync",
                                        "Received workout history chunk without index! Falling back to append behavior."
                                    )
                                    val currentChunks = workoutHistoryChunks.toMutableMap()
                                    val nextIndex = currentChunks.keys.maxOrNull()?.plus(1) ?: 0
                                    currentChunks[nextIndex] = workoutHistoryChunk
                                    workoutHistoryChunks = currentChunks

                                    val currentIndices = receivedChunkIndices.toMutableSet()
                                    currentIndices.add(nextIndex)
                                    receivedChunkIndices = currentIndices
                                }
                            }

                            if (isLastChunk || isLastRetryChunk) {
                                Log.d(
                                    "DataLayerSync",
                                    "Received last workout history chunk (isLastChunk: $isLastChunk, isLastRetryChunk: $isLastRetryChunk). Total chunks received: ${workoutHistoryChunks.size}, expected: $expectedChunks"
                                )
                                if (!ignoreUntilStartOrEnd) {
                                    scope.launch(Dispatchers.IO) {
                                        var processingStep = "initialization"
                                        try {
                                            processingStep = "validating chunks"
                                            
                                            // Log chunk reception details
                                            val chunkReceptionStartTime = System.currentTimeMillis()
                                            val receivedIndicesList = receivedChunkIndices.sorted()
                                            Log.d(
                                                "DataLayerSync",
                                                "Chunk validation for transaction: $transactionId - Expected: $expectedChunks, Received: ${workoutHistoryChunks.size}, Received indices: $receivedIndicesList"
                                            )
                                            
                                            // Check connection state during validation - fail fast if disconnected
                                            val isConnected = checkConnectionDuringSync(transactionId)
                                            if (!isConnected) {
                                                throw IllegalStateException("Connection lost during chunk validation for transaction: $transactionId")
                                            }

                                            // Validate that all expected chunks are present
                                            val missingIndices = mutableListOf<Int>()
                                            for (i in 0 until expectedChunks) {
                                                if (i !in receivedChunkIndices) {
                                                    missingIndices.add(i)
                                                }
                                            }
                                            
                                            // Log timing information
                                            val validationTime = System.currentTimeMillis() - chunkReceptionStartTime
                                            Log.d(
                                                "DataLayerSync",
                                                "Chunk validation completed in ${validationTime}ms for transaction: $transactionId"
                                            )

                                            if (missingIndices.isNotEmpty()) {
                                                Log.e(
                                                    "DataLayerSync",
                                                    "Validation failed: Missing chunks. Expected: $expectedChunks, Received: ${workoutHistoryChunks.size}, Missing indices: $missingIndices, Validation time: ${validationTime}ms"
                                                )
                                                // Log chunk delivery metrics
                                                val deliveryRate = (workoutHistoryChunks.size.toFloat() / expectedChunks * 100).toInt()
                                                Log.e(
                                                    "DataLayerSync",
                                                    "Chunk delivery metrics - Delivery rate: $deliveryRate%, Missing: ${missingIndices.size}, Transaction: $transactionId"
                                                )

                                                // Send SYNC_ERROR with missing chunk information (triggers retry on sender)
                                                transactionId?.let { tid ->
                                                    try {
                                                        val errorMessage =
                                                            "MISSING_CHUNKS: Expected $expectedChunks chunks, received ${workoutHistoryChunks.size}. Missing indices: $missingIndices"
                                                        Log.e(
                                                            "DataLayerSync",
                                                            "Sending SYNC_ERROR for transaction: $tid due to missing chunks"
                                                        )
                                                        val errorPath = DataLayerPaths.buildPath(
                                                            DataLayerPaths.SYNC_ERROR_PREFIX,
                                                            tid
                                                        )
                                                        val errorDataMapRequest =
                                                            PutDataMapRequest.create(errorPath)
                                                        errorDataMapRequest.dataMap.putString(
                                                            "transactionId",
                                                            tid
                                                        )
                                                        errorDataMapRequest.dataMap.putString(
                                                            "errorMessage",
                                                            errorMessage
                                                        )
                                                        errorDataMapRequest.dataMap.putString(
                                                            "timestamp",
                                                            System.currentTimeMillis().toString()
                                                        )

                                                        val errorRequest =
                                                            errorDataMapRequest.asPutDataRequest()
                                                                .setUrgent()
                                                        val task =
                                                            dataClient.putDataItem(errorRequest)
                                                        Tasks.await(task)
                                                        Log.e(
                                                            "DataLayerSync",
                                                            "Successfully sent SYNC_ERROR for transaction: $tid"
                                                        )
                                                    } catch (sendErrorException: Exception) {
                                                        Log.e(
                                                            "DataLayerSync",
                                                            "Failed to send SYNC_ERROR for transaction: $tid",
                                                            sendErrorException
                                                        )
                                                    }
                                                }

                                                // Don't clear chunk state yet - may receive retry chunks
                                                // Don't send broadcast to dismiss loading screen - keep syncing screen visible for retry
                                                return@launch
                                            }

                                            // Check connection again before processing - fail fast if disconnected
                                            val isConnectedBeforeProcessing = checkConnectionDuringSync(transactionId)
                                            if (!isConnectedBeforeProcessing) {
                                                throw IllegalStateException("Connection lost before processing for transaction: $transactionId")
                                            }
                                            
                                            // All chunks present - proceed with processing
                                            processingStep = "combining chunks"
                                            Log.d(
                                                "DataLayerSync",
                                                "All chunks validated. Combining ${workoutHistoryChunks.size} chunks for transaction: $transactionId"
                                            )

                                            // Combine chunks in index order
                                            val sortedChunks =
                                                (0 until expectedChunks).mapNotNull { index ->
                                                    workoutHistoryChunks[index]
                                                }

                                            if (sortedChunks.size != expectedChunks) {
                                                throw IllegalStateException("Expected $expectedChunks chunks but only ${sortedChunks.size} found after validation")
                                            }

                                            val compressedData = combineChunks(sortedChunks)

                                            processingStep = "decompressing workout history data"
                                            Log.d(
                                                "DataLayerSync",
                                                "Decompressing workout history data (size: ${compressedData.size} bytes) for transaction: $transactionId"
                                            )
                                            val workoutHistoryStoreJson =
                                                decompressToString(compressedData)

                                            processingStep = "parsing JSON workout history"
                                            Log.d(
                                                "DataLayerSync",
                                                "Parsing JSON workout history (length: ${workoutHistoryStoreJson.length} chars) for transaction: $transactionId"
                                            )
                                            val gson = GsonBuilder()
                                                .registerTypeAdapter(
                                                    LocalDate::class.java,
                                                    LocalDateAdapter()
                                                )
                                                .registerTypeAdapter(
                                                    LocalTime::class.java,
                                                    LocalTimeAdapter()
                                                )
                                                .registerTypeAdapter(
                                                    LocalDateTime::class.java,
                                                    LocalDateTimeAdapter()
                                                )
                                                .registerTypeAdapter(
                                                    SetData::class.java,
                                                    SetDataAdapter()
                                                )
                                                .create()

                                            val workoutHistoryStore = workoutHistoryGson.fromJson(
                                                workoutHistoryStoreJson,
                                                WorkoutHistoryStore::class.java
                                            )

                                            processingStep = "processing workout history"
                                            Log.d(
                                                "DataLayerSync",
                                                "Processing workout history for transaction: $transactionId"
                                            )

                                            val workoutStore =
                                                workoutStoreRepository.getWorkoutStore()
                                            val workout =
                                                workoutStore.workouts.find { it.id == workoutHistoryStore.WorkoutHistory.workoutId }

                                            if (workout == null) {
                                                throw IllegalStateException("Workout not found for workout history: ${workoutHistoryStore.WorkoutHistory.workoutId}")
                                            }

                                            // Wrap database operations in NonCancellable to ensure they complete even if service is destroyed
                                            withContext(NonCancellable) {
                                                workoutHistoryDao.insertWithVersionCheck(
                                                    workoutHistoryStore.WorkoutHistory
                                                )
                                                setHistoryDao.insertAllWithVersionCheck(*workoutHistoryStore.SetHistories.toTypedArray())

                                                if (workoutHistoryStore.WorkoutRecord != null) {
                                                    workoutRecordDao.deleteByWorkoutId(workout.id)
                                                    workoutRecordDao.insert(workoutHistoryStore.WorkoutRecord!!)
                                                }

                                                if (workoutHistoryStore.WorkoutHistory.isDone) {
                                                    exerciseInfoDao.insertAllWithVersionCheck(*workoutHistoryStore.ExerciseInfos.toTypedArray())
                                                    exerciseSessionProgressionDao.insertAllWithVersionCheck(
                                                        *workoutHistoryStore.ExerciseSessionProgressions.toTypedArray()
                                                    )
                                                    workoutRecordDao.deleteByWorkoutId(workout.id)

                                                    val setHistoriesByExerciseId =
                                                        workoutHistoryStore.SetHistories
                                                            .filter { it.exerciseId != null }
                                                            .groupBy { it.exerciseId }

                                                    val exercises =
                                                        workout.workoutComponents.filterIsInstance<Exercise>() + workout.workoutComponents.filterIsInstance<Superset>()
                                                            .flatMap { it.exercises }
                                                    var workoutComponents =
                                                        workout.workoutComponents

                                                    for (exercise in exercises) {
                                                        if (exercise.doNotStoreHistory) continue
                                                        val setHistories =
                                                            setHistoriesByExerciseId[exercise.id]?.sortedBy { it.order }
                                                                ?: continue

                                                        workoutComponents =
                                                            removeSetsFromExerciseRecursively(
                                                                workoutComponents,
                                                                exercise
                                                            )

                                                        val validSetHistories = setHistories
                                                            .dropWhile { it.setData is RestSetData }
                                                            .dropLastWhile { it.setData is RestSetData }
                                                            .filter { it ->
                                                                when (val setData = it.setData) {
                                                                    is BodyWeightSetData -> setData.subCategory != SetSubCategory.RestPauseSet
                                                                    is WeightSetData -> setData.subCategory != SetSubCategory.RestPauseSet
                                                                    is RestSetData -> setData.subCategory != SetSubCategory.RestPauseSet
                                                                    else -> true
                                                                }
                                                            }

                                                        for (setHistory in validSetHistories) {
                                                            val newSet =
                                                                getNewSetFromSetHistory(setHistory)
                                                            workoutComponents =
                                                                addSetToExerciseRecursively(
                                                                    workoutComponents,
                                                                    exercise,
                                                                    newSet,
                                                                    setHistory.order
                                                                )
                                                        }
                                                    }

                                                    val newWorkout =
                                                        workout.copy(workoutComponents = workoutComponents)
                                                    val updatedWorkoutStore = workoutStore.copy(
                                                        workouts = updateWorkoutOld(
                                                            workoutStore.workouts,
                                                            workout,
                                                            newWorkout
                                                        )
                                                    )
                                                    workoutStoreRepository.saveWorkoutStore(
                                                        updatedWorkoutStore
                                                    )
                                                    val db =
                                                        AppDatabase.getDatabase(this@DataLayerListenerService)
                                                    saveWorkoutStoreToDownloads(
                                                        this@DataLayerListenerService,
                                                        updatedWorkoutStore,
                                                        db
                                                    )
                                                }

                                                // Save error logs if present
                                                if (workoutHistoryStore.ErrorLogs.isNotEmpty()) {
                                                    errorLogDao.insertAll(*workoutHistoryStore.ErrorLogs.toTypedArray())
                                                }
                                            }

                                            val intent = Intent(INTENT_ID).apply {
                                                putExtra(UPDATE_WORKOUTS, UPDATE_WORKOUTS)
                                            }

                                            intent.apply { setPackage(packageName) }
                                            sendBroadcast(intent)

                                            // Send completion acknowledgment
                                            transactionId?.let { tid ->
                                                try {
                                                    Log.d(
                                                        "DataLayerSync",
                                                        "Preparing to send SYNC_COMPLETE for transaction: $tid (workout history processed)"
                                                    )
                                                    val completePath = DataLayerPaths.buildPath(
                                                        DataLayerPaths.SYNC_COMPLETE_PREFIX,
                                                        tid
                                                    )
                                                    val completeDataMapRequest =
                                                        PutDataMapRequest.create(completePath)
                                                    completeDataMapRequest.dataMap.putString(
                                                        "transactionId",
                                                        tid
                                                    )
                                                    val timestamp =
                                                        System.currentTimeMillis().toString()
                                                    completeDataMapRequest.dataMap.putString(
                                                        "timestamp",
                                                        timestamp
                                                    )

                                                    val completeRequest =
                                                        completeDataMapRequest.asPutDataRequest()
                                                            .setUrgent()
                                                    Log.d(
                                                        "DataLayerSync",
                                                        "Sending SYNC_COMPLETE for transaction: $tid, timestamp: $timestamp"
                                                    )
                                                    val task =
                                                        dataClient.putDataItem(completeRequest)
                                                    Tasks.await(task)
                                                    Log.d(
                                                        "DataLayerSync",
                                                        "Successfully sent SYNC_COMPLETE for transaction: $tid (workout history)"
                                                    )
                                                } catch (exception: Exception) {
                                                    Log.e(
                                                        "DataLayerSync",
                                                        "Failed to send SYNC_COMPLETE for transaction: $tid",
                                                        exception
                                                    )
                                                }
                                            }

                                            // Clean up chunk state after successful processing
                                            workoutHistoryChunks = mutableMapOf()
                                            receivedChunkIndices = mutableSetOf()
                                            expectedChunks = 0
                                            hasStartedSync = false
                                            ignoreUntilStartOrEnd = false
                                            currentTransactionId = null
                                        } catch (exception: Exception) {
                                            // Build comprehensive error message
                                            val exceptionClassName = exception.javaClass.simpleName
                                            val exceptionMessage = exception.message

                                            // Build error message with safe length limit
                                            val fullErrorMessage = when {
                                                exceptionMessage != null && exceptionMessage.isNotEmpty() -> {
                                                    "$exceptionClassName at $processingStep: $exceptionMessage"
                                                }

                                                else -> {
                                                    "$exceptionClassName at $processingStep: Unknown error processing workout history"
                                                }
                                            }

                                            // Truncate if too long
                                            val errorMessage = if (fullErrorMessage.length > 1000) {
                                                fullErrorMessage.take(997) + "..."
                                            } else {
                                                fullErrorMessage
                                            }

                                            Log.e(
                                                "DataLayerSync",
                                                "Error processing workout history at step: $processingStep",
                                                exception
                                            )
                                            Log.e(
                                                "DataLayerSync",
                                                "Exception type: $exceptionClassName, message: $exceptionMessage"
                                            )
                                            exception.printStackTrace()

                                            // Send error response back to sender
                                            transactionId?.let { tid ->
                                                try {
                                                    Log.e(
                                                        "DataLayerSync",
                                                        "Sending SYNC_ERROR for transaction: $tid due to workout history processing error"
                                                    )
                                                    val errorPath = DataLayerPaths.buildPath(
                                                        DataLayerPaths.SYNC_ERROR_PREFIX,
                                                        tid
                                                    )
                                                    val errorDataMapRequest =
                                                        PutDataMapRequest.create(errorPath)
                                                    errorDataMapRequest.dataMap.putString(
                                                        "transactionId",
                                                        tid
                                                    )
                                                    errorDataMapRequest.dataMap.putString(
                                                        "errorMessage",
                                                        errorMessage
                                                    )
                                                    errorDataMapRequest.dataMap.putString(
                                                        "timestamp",
                                                        System.currentTimeMillis().toString()
                                                    )

                                                    val errorRequest =
                                                        errorDataMapRequest.asPutDataRequest()
                                                            .setUrgent()
                                                    val task = dataClient.putDataItem(errorRequest)
                                                    Tasks.await(task)
                                                    Log.e(
                                                        "DataLayerSync",
                                                        "Successfully sent SYNC_ERROR for transaction: $tid"
                                                    )
                                                } catch (sendErrorException: Exception) {
                                                    Log.e(
                                                        "DataLayerSync",
                                                        "Failed to send SYNC_ERROR for transaction: $tid",
                                                        sendErrorException
                                                    )
                                                }
                                            }

                                            // Clean up state after error (operation failed, no retries will happen)
                                            workoutHistoryChunks = mutableMapOf()
                                            receivedChunkIndices = mutableSetOf()
                                            expectedChunks = 0
                                            hasStartedSync = false
                                            ignoreUntilStartOrEnd = false
                                            currentTransactionId = null
                                        }
                                    }
                                }
                            }
                        } // End of workout history path handling
                    }

                    path == OPEN_PAGE_PATH -> {
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

                    path == CLEAR_ERROR_LOGS_PATH -> {
                        scope.launch(Dispatchers.IO) {
                            try {
                                errorLogDao.deleteAll()
                                Log.d("DataLayerListenerService", "Error logs cleared from mobile")
                            } catch (e: Exception) {
                                Log.e("DataLayerListenerService", "Error clearing error logs", e)
                            }
                        }
                    }

                    path == ERROR_LOGS_SYNC_PATH -> {
                        val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                        val compressedJson = dataMap.getByteArray("compressedJson")

                        scope.launch(Dispatchers.IO) {
                            try {
                                val errorLogsJson = decompressToString(compressedJson!!)

                                val gson = GsonBuilder()
                                    .registerTypeAdapter(
                                        LocalDateTime::class.java,
                                        LocalDateTimeAdapter()
                                    )
                                    .create()

                                val errorLogs = gson.fromJson(
                                    errorLogsJson,
                                    Array<ErrorLog>::class.java
                                ).toList()

                                if (errorLogs.isNotEmpty()) {
                                    errorLogDao.insertAll(*errorLogs.toTypedArray())
                                    Log.d(
                                        "DataLayerListenerService",
                                        "Synced ${errorLogs.size} error logs from watch"
                                    )

                                    // Send broadcast to show toast notification
                                    val intent = Intent(INTENT_ID).apply {
                                        putExtra(ERROR_LOGS_SYNCED, errorLogs.size.toString())
                                    }
                                    intent.apply { setPackage(packageName) }
                                    sendBroadcast(intent)
                                }
                            } catch (exception: Exception) {
                                Log.e(
                                    "DataLayerListenerService",
                                    "Error processing error logs sync",
                                    exception
                                )
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
        private const val WORKOUT_HISTORY_CHUNK_PATH = "/workoutHistoryChunkPath"
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
        const val SYNC_ERROR_PATH = "/syncError"
        const val HANDSHAKE_TIMEOUT_MS = 15000L // Increased from 5000L for slow connections
        const val COMPLETION_TIMEOUT_MS =
            30000L // Legacy constant, use calculateCompletionTimeout instead
        const val BASE_COMPLETION_TIMEOUT_MS = 10000L
        const val PER_CHUNK_TIMEOUT_MS = 2000L
        const val MAX_COMPLETION_TIMEOUT_MS = 300000L // 5 minutes
        
        // SharedPreferences keys for configurable timeouts
        private const val PREF_HANDSHAKE_TIMEOUT = "handshake_timeout_ms"
        private const val PREF_BASE_COMPLETION_TIMEOUT = "base_completion_timeout_ms"
        private const val PREF_PER_CHUNK_TIMEOUT = "per_chunk_timeout_ms"
        private const val PREF_CONNECTION_QUALITY = "connection_quality_multiplier"

        /**
         * Gets handshake timeout, configurable via SharedPreferences with default fallback.
         * Connection quality multiplier adjusts timeout for poor connections.
         */
        fun getHandshakeTimeout(context: Context): Long {
            val prefs = context.getSharedPreferences("sync_timeouts", Context.MODE_PRIVATE)
            val baseTimeout = prefs.getLong(PREF_HANDSHAKE_TIMEOUT, HANDSHAKE_TIMEOUT_MS).toFloat()
            val qualityMultiplier = prefs.getFloat(PREF_CONNECTION_QUALITY, 1.0f).coerceIn(0.5f, 2.0f)
            return (baseTimeout * qualityMultiplier).toLong()
        }

        /**
         * Calculates dynamic completion timeout based on chunk count.
         * Formula: baseMs + perChunkMs * chunksCount, clamped to max.
         * Connection quality multiplier adjusts timeout for poor connections.
         */
        fun calculateCompletionTimeout(context: Context, chunksCount: Int): Long {
            val prefs = context.getSharedPreferences("sync_timeouts", Context.MODE_PRIVATE)
            val baseTimeout = prefs.getLong(PREF_BASE_COMPLETION_TIMEOUT, BASE_COMPLETION_TIMEOUT_MS).toFloat()
            val perChunkTimeout = prefs.getLong(PREF_PER_CHUNK_TIMEOUT, PER_CHUNK_TIMEOUT_MS).toFloat()
            val qualityMultiplier = prefs.getFloat(PREF_CONNECTION_QUALITY, 1.0f).coerceIn(0.5f, 2.0f)
            
            val calculated = (baseTimeout + perChunkTimeout * chunksCount) * qualityMultiplier
            return minOf(calculated.toLong(), MAX_COMPLETION_TIMEOUT_MS)
        }
        
        /**
         * Legacy method for backward compatibility - uses default timeouts without context.
         */
        fun calculateCompletionTimeout(chunksCount: Int): Long {
            val calculated = BASE_COMPLETION_TIMEOUT_MS + PER_CHUNK_TIMEOUT_MS * chunksCount
            return minOf(calculated, MAX_COMPLETION_TIMEOUT_MS)
        }
        
        /**
         * Updates connection quality multiplier based on recent sync performance.
         * Higher multiplier = longer timeouts for poor connections.
         */
        fun updateConnectionQuality(context: Context, recentTimeouts: Int, recentSuccesses: Int) {
            val prefs = context.getSharedPreferences("sync_timeouts", Context.MODE_PRIVATE)
            val total = recentTimeouts + recentSuccesses
            if (total > 0) {
                val timeoutRate = recentTimeouts.toFloat() / total
                val multiplier = when {
                    timeoutRate > 0.5f -> 1.5f // Poor connection - increase timeouts
                    timeoutRate > 0.3f -> 1.2f // Moderate issues
                    else -> 1.0f // Good connection
                }
                prefs.edit().putFloat(PREF_CONNECTION_QUALITY, multiplier).apply()
                Log.d("DataLayerSync", "Updated connection quality multiplier to $multiplier (timeout rate: $timeoutRate)")
            }
        }
    }
}
