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
import kotlin.io.encoding.Base64
import kotlin.io.encoding.ExperimentalEncodingApi
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

    private val sharedPreferences by lazy { getSharedPreferences("workout_history_sync_state", Context.MODE_PRIVATE) }
    private val gson = Gson()

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
                        Log.e("DataLayerListenerService", "Failed to decode chunk at index $indexStr: ${e.message}")
                        null
                    }
                }.toMap().toMutableMap()
            } catch (e: Exception) {
                Log.e("DataLayerListenerService", "Failed to parse workoutHistoryChunks from SharedPreferences with Gson: ${e.message}", e)
                sharedPreferences.edit { remove("workout_history_chunks") }
                mutableMapOf()
            }
        }
        set(value) {
            if (value.isEmpty()) {
                sharedPreferences.edit { remove("workout_history_chunks") }
            } else {
                try {
                    val base64Map = value.mapKeys { it.key.toString() }.mapValues { (_, byteArray) ->
                        Base64.encode(byteArray)
                    }
                    val jsonString = gson.toJson(base64Map)
                    sharedPreferences.edit { putString("workout_history_chunks", jsonString) }
                } catch (e: Exception) {
                    Log.e("DataLayerListenerService", "Failed to save workoutHistoryChunks to SharedPreferences with Gson: ${e.message}", e)
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
            sharedPreferences.edit() { putBoolean("ignore_workout_history_until_start_or_end", value) }
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
                sharedPreferences.edit() { putString("current_workout_history_transaction_id", value) }
            }
        }

    private var receivedChunkIndices: MutableSet<Int>
        get() {
            val indicesString = sharedPreferences.getString("received_workout_history_chunk_indices", null)
            if (indicesString.isNullOrEmpty()) {
                return mutableSetOf()
            }
            return try {
                val typeToken = object : TypeToken<List<Int>>() {}.type
                val indices: List<Int> = gson.fromJson(indicesString, typeToken)
                indices.toMutableSet()
            } catch (e: Exception) {
                Log.e("DataLayerListenerService", "Failed to parse receivedChunkIndices: ${e.message}", e)
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
                    sharedPreferences.edit { putString("received_workout_history_chunk_indices", jsonString) }
                } catch (e: Exception) {
                    Log.e("DataLayerListenerService", "Failed to save receivedChunkIndices: ${e.message}", e)
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
                        val timestampStr = dataMap.getString("timestamp")
                        
                        // Ignore ACKs without transactionId
                        if (transactionId == null) {
                            Log.w("DataLayerSync", "Received SYNC_ACK without transactionId - ignoring stale message")
                            return@forEach
                        }
                        
                        // Ignore stale ACKs (older than 30 seconds)
                        if (timestampStr != null) {
                            try {
                                val timestamp = timestampStr.toLong()
                                val currentTime = System.currentTimeMillis()
                                val age = currentTime - timestamp
                                if (age > 30000) {
                                    Log.w("DataLayerSync", "Received stale SYNC_ACK for transaction: $transactionId (age: ${age}ms) - ignoring")
                                    return@forEach
                                }
                            } catch (e: NumberFormatException) {
                                Log.w("DataLayerSync", "Received SYNC_ACK with invalid timestamp format for transaction: $transactionId")
                            }
                        }
                        
                        Log.d("DataLayerSync", "Received SYNC_ACK for transaction: $transactionId")
                        SyncHandshakeManager.completeAck(transactionId)
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
                    SYNC_ERROR_PATH -> {
                        val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                        val transactionId = dataMap.getString("transactionId")
                        val errorMessage = dataMap.getString("errorMessage", "Unknown error")
                        if (transactionId != null) {
                            Log.e("DataLayerSync", "Received SYNC_ERROR for transaction: $transactionId, error: $errorMessage")
                            SyncHandshakeManager.completeError(transactionId, errorMessage)
                        } else {
                            Log.w("DataLayerSync", "Received SYNC_ERROR without transactionId, error: $errorMessage")
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
                            exception.printStackTrace()
                            
                            // Send error response back to sender
                            transactionId?.let { tid ->
                                try {
                                    Log.e("DataLayerSync", "Sending SYNC_ERROR for transaction: $tid due to processing error")
                                    val errorMessage = exception.message ?: "Unknown error processing workout history store"
                                    val errorDataMapRequest = PutDataMapRequest.create(SYNC_ERROR_PATH)
                                    errorDataMapRequest.dataMap.putString("transactionId", tid)
                                    errorDataMapRequest.dataMap.putString("errorMessage", errorMessage)
                                    errorDataMapRequest.dataMap.putString("timestamp", System.currentTimeMillis().toString())
                                    
                                    val errorRequest = errorDataMapRequest.asPutDataRequest().setUrgent()
                                    val task = dataClient.putDataItem(errorRequest)
                                    Tasks.await(task)
                                    Log.e("DataLayerSync", "Successfully sent SYNC_ERROR for transaction: $tid")
                                } catch (sendErrorException: Exception) {
                                    Log.e("DataLayerSync", "Failed to send SYNC_ERROR for transaction: $tid", sendErrorException)
                                }
                            }
                        }
                        }
                    }

                    WORKOUT_HISTORY_CHUNK_PATH -> {
                        val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap

                        val isStart = dataMap.getBoolean("isStart", false)
                        val isLastChunk = dataMap.getBoolean("isLastChunk", false)
                        val workoutHistoryChunk = dataMap.getByteArray("chunk")
                        val transactionId = dataMap.getString("transactionId")
                        val isRetry = dataMap.getBoolean("isRetry", false)
                        val isLastRetryChunk = dataMap.getBoolean("isLastRetryChunk", false)
                        val chunkIndex = if (dataMap.containsKey("chunkIndex")) dataMap.getInt("chunkIndex", -1) else -1

                        // Retry chunks with same transaction ID should not trigger shouldStop
                        val shouldStop = !isRetry && (
                                (isStart && hasStartedSync) ||
                                (workoutHistoryChunk != null && !hasStartedSync) ||
                                (currentTransactionId != null && currentTransactionId != transactionId)
                        )

                        Log.d("DataLayerListenerService", "ignoreUntilStartOrEnd: $ignoreUntilStartOrEnd hasWorkoutHistoryChunk: ${workoutHistoryChunk != null} isStart: $isStart isLastChunk: $isLastChunk isRetry: $isRetry chunkIndex: $chunkIndex transactionId: $transactionId shouldStop: $shouldStop")

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

                            Log.d("DataLayerSync", "Workout history backup started with expected chunks: $expectedChunks, transactionId: $transactionId")

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

                                Log.d("DataLayerSync", "Received workout history chunk at index $chunkIndex. Total chunks: ${workoutHistoryChunks.size}, expected: $expectedChunks, isRetry: $isRetry")
                            } else {
                                // Fallback for backwards compatibility - should not happen with new implementation
                                Log.w("DataLayerSync", "Received workout history chunk without index! Falling back to append behavior.")
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
                            Log.d("DataLayerSync", "Received last workout history chunk (isLastChunk: $isLastChunk, isLastRetryChunk: $isLastRetryChunk). Total chunks received: ${workoutHistoryChunks.size}, expected: $expectedChunks")
                            if (!ignoreUntilStartOrEnd) {
                                scope.launch(Dispatchers.IO) {
                                    var processingStep = "initialization"
                                    try {
                                        processingStep = "validating chunks"
                                        
                                        // Validate that all expected chunks are present
                                        val missingIndices = mutableListOf<Int>()
                                        for (i in 0 until expectedChunks) {
                                            if (i !in receivedChunkIndices) {
                                                missingIndices.add(i)
                                            }
                                        }
                                        
                                        if (missingIndices.isNotEmpty()) {
                                            Log.e("DataLayerSync", "Validation failed: Missing chunks. Expected: $expectedChunks, Received: ${workoutHistoryChunks.size}, Missing indices: $missingIndices")
                                            
                                            // Send SYNC_ERROR with missing chunk information (triggers retry on sender)
                                            transactionId?.let { tid ->
                                                try {
                                                    val errorMessage = "MISSING_CHUNKS: Expected $expectedChunks chunks, received ${workoutHistoryChunks.size}. Missing indices: $missingIndices"
                                                    Log.e("DataLayerSync", "Sending SYNC_ERROR for transaction: $tid due to missing chunks")
                                                    val errorDataMapRequest = PutDataMapRequest.create(SYNC_ERROR_PATH)
                                                    errorDataMapRequest.dataMap.putString("transactionId", tid)
                                                    errorDataMapRequest.dataMap.putString("errorMessage", errorMessage)
                                                    errorDataMapRequest.dataMap.putString("timestamp", System.currentTimeMillis().toString())
                                                    
                                                    val errorRequest = errorDataMapRequest.asPutDataRequest().setUrgent()
                                                    val task = dataClient.putDataItem(errorRequest)
                                                    Tasks.await(task)
                                                    Log.e("DataLayerSync", "Successfully sent SYNC_ERROR for transaction: $tid")
                                                } catch (sendErrorException: Exception) {
                                                    Log.e("DataLayerSync", "Failed to send SYNC_ERROR for transaction: $tid", sendErrorException)
                                                }
                                            }
                                            
                                            // Don't clear chunk state yet - may receive retry chunks
                                            // Don't send broadcast to dismiss loading screen - keep syncing screen visible for retry
                                            return@launch
                                        }
                                        
                                        // All chunks present - proceed with processing
                                        processingStep = "combining chunks"
                                        Log.d("DataLayerSync", "All chunks validated. Combining ${workoutHistoryChunks.size} chunks for transaction: $transactionId")
                                        
                                        // Combine chunks in index order
                                        val sortedChunks = (0 until expectedChunks).mapNotNull { index ->
                                            workoutHistoryChunks[index]
                                        }
                                        
                                        if (sortedChunks.size != expectedChunks) {
                                            throw IllegalStateException("Expected $expectedChunks chunks but only ${sortedChunks.size} found after validation")
                                        }
                                        
                                        val compressedData = combineChunks(sortedChunks)
                                        
                                        processingStep = "decompressing workout history data"
                                        Log.d("DataLayerSync", "Decompressing workout history data (size: ${compressedData.size} bytes) for transaction: $transactionId")
                                        val workoutHistoryStoreJson = decompressToString(compressedData)
                                        
                                        processingStep = "parsing JSON workout history"
                                        Log.d("DataLayerSync", "Parsing JSON workout history (length: ${workoutHistoryStoreJson.length} chars) for transaction: $transactionId")
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

                                        processingStep = "processing workout history"
                                        Log.d("DataLayerSync", "Processing workout history for transaction: $transactionId")

                                        val workoutStore = workoutStoreRepository.getWorkoutStore()
                                        val workout = workoutStore.workouts.find { it.id == workoutHistoryStore.WorkoutHistory.workoutId }

                                        if(workout == null) {
                                            throw IllegalStateException("Workout not found for workout history: ${workoutHistoryStore.WorkoutHistory.workoutId}")
                                        }

                                        // Wrap database operations in NonCancellable to ensure they complete even if service is destroyed
                                        withContext(NonCancellable) {
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
                                            } catch (exception: Exception) {
                                                Log.e("DataLayerSync", "Failed to send SYNC_COMPLETE for transaction: $tid", exception)
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
                                        
                                        Log.e("DataLayerSync", "Error processing workout history at step: $processingStep", exception)
                                        Log.e("DataLayerSync", "Exception type: $exceptionClassName, message: $exceptionMessage")
                                        exception.printStackTrace()
                                        
                                        // Send error response back to sender
                                        transactionId?.let { tid ->
                                            try {
                                                Log.e("DataLayerSync", "Sending SYNC_ERROR for transaction: $tid due to workout history processing error")
                                                val errorDataMapRequest = PutDataMapRequest.create(SYNC_ERROR_PATH)
                                                errorDataMapRequest.dataMap.putString("transactionId", tid)
                                                errorDataMapRequest.dataMap.putString("errorMessage", errorMessage)
                                                errorDataMapRequest.dataMap.putString("timestamp", System.currentTimeMillis().toString())
                                                
                                                val errorRequest = errorDataMapRequest.asPutDataRequest().setUrgent()
                                                val task = dataClient.putDataItem(errorRequest)
                                                Tasks.await(task)
                                                Log.e("DataLayerSync", "Successfully sent SYNC_ERROR for transaction: $tid")
                                            } catch (sendErrorException: Exception) {
                                                Log.e("DataLayerSync", "Failed to send SYNC_ERROR for transaction: $tid", sendErrorException)
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
        const val HANDSHAKE_TIMEOUT_MS = 5000L
        const val COMPLETION_TIMEOUT_MS = 30000L
    }
}
