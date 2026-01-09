package com.gabstra.myworkoutassistant

import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.widget.Toast
import androidx.core.content.edit
import com.gabstra.myworkoutassistant.data.combineChunks
import com.gabstra.myworkoutassistant.data.showSyncCompleteNotification
import com.gabstra.myworkoutassistant.scheduling.WorkoutAlarmScheduler
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.ExerciseInfoDao
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgressionDao
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutRecordDao
import com.gabstra.myworkoutassistant.shared.WorkoutScheduleDao
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.decompressToString
import com.gabstra.myworkoutassistant.shared.fromJSONtoAppBackup
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.google.android.gms.tasks.Tasks
import com.google.android.gms.wearable.DataEventBuffer
import com.google.android.gms.wearable.DataMapItem
import com.google.android.gms.wearable.PutDataMapRequest
import com.google.android.gms.wearable.Wearable
import com.google.android.gms.wearable.WearableListenerService
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.joinAll
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import java.util.UUID
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

    private val sharedPreferences by lazy { getSharedPreferences("backup_state", Context.MODE_PRIVATE) }
    private val gson = Gson()

    @OptIn(ExperimentalEncodingApi::class)
    private var backupChunks: MutableMap<Int, ByteArray>
        get() {
            val jsonString = sharedPreferences.getString("backup_chunks", null)
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
                Log.e("DataLayerListenerService", "Failed to parse backupChunks from SharedPreferences with Gson: ${e.message}", e)
                sharedPreferences.edit { remove("backup_chunks") }
                mutableMapOf()
            }
        }
        set(value) {
            if (value.isEmpty()) {
                sharedPreferences.edit { remove("backup_chunks") }
            } else {
                try {
                    val base64Map = value.mapKeys { it.key.toString() }.mapValues { (_, byteArray) ->
                        Base64.encode(byteArray)
                    }
                    val jsonString = gson.toJson(base64Map)
                    sharedPreferences.edit { putString("backup_chunks", jsonString) }
                } catch (e: Exception) {
                    Log.e("DataLayerListenerService", "Failed to save backupChunks to SharedPreferences with Gson: ${e.message}", e)
                }
            }
        }

    private var expectedChunks: Int
        get() = sharedPreferences.getInt("expectedChunks", 0)
        set(value) {
            sharedPreferences.edit() { putInt("expectedChunks", value) }
        }

    private var ignoreUntilStartOrEnd: Boolean
        get() = sharedPreferences.getBoolean("ignoreUntilStartOrEnd", false)
        set(value) {
            sharedPreferences.edit() { putBoolean("ignoreUntilStartOrEnd", value) }
        }

    private var hasStartedSync: Boolean
        get() = sharedPreferences.getBoolean("hasStartedSync", false)
        set(value) {
            sharedPreferences.edit() { putBoolean("hasStartedSync", value) }
        }

    private var currentTransactionId: String?
        get() = sharedPreferences.getString("currentTransactionId", null)
        set(value) {
            if (value == null) {
                sharedPreferences.edit() { remove("currentTransactionId") }
            } else {
                sharedPreferences.edit() { putString("currentTransactionId", value) }
            }
        }

    private var receivedChunkIndices: MutableSet<Int>
        get() {
            val indicesString = sharedPreferences.getString("receivedChunkIndices", null)
            if (indicesString.isNullOrEmpty()) {
                return mutableSetOf()
            }
            return try {
                val typeToken = object : TypeToken<List<Int>>() {}.type
                val indices: List<Int> = gson.fromJson(indicesString, typeToken)
                indices.toMutableSet()
            } catch (e: Exception) {
                Log.e("DataLayerListenerService", "Failed to parse receivedChunkIndices: ${e.message}", e)
                sharedPreferences.edit { remove("receivedChunkIndices") }
                mutableSetOf()
            }
        }
        set(value) {
            if (value.isEmpty()) {
                sharedPreferences.edit { remove("receivedChunkIndices") }
            } else {
                try {
                    val jsonString = gson.toJson(value.toList())
                    sharedPreferences.edit { putString("receivedChunkIndices", jsonString) }
                } catch (e: Exception) {
                    Log.e("DataLayerListenerService", "Failed to save receivedChunkIndices: ${e.message}", e)
                }
            }
        }

    private lateinit var workoutScheduleDao: WorkoutScheduleDao

    private lateinit var context : WearableListenerService

    override fun onCreate() {
        super.onCreate()
        val db = AppDatabase.getDatabase(this)
        context = this
        setHistoryDao = db.setHistoryDao()
        workoutHistoryDao = db.workoutHistoryDao()
        exerciseInfoDao = db.exerciseInfoDao()
        workoutScheduleDao = db.workoutScheduleDao()
        workoutRecordDao = db.workoutRecordDao()
        exerciseSessionProgressionDao = db.exerciseSessionProgressionDao()
    }

    private val handler = Handler(Looper.getMainLooper())

    @Volatile // Ensure visibility across threads
    private var timeoutOperationCancelled = false

    private val timeoutRunnable = Runnable {
        if (timeoutOperationCancelled) {
            return@Runnable // Exit if cancelled
        }
        Log.d("DataLayerListenerService", "Timeout triggered")

        val intent = Intent(INTENT_ID).apply {
            putExtra(APP_BACKUP_FAILED, APP_BACKUP_FAILED)
            setPackage(packageName)
        }
        sendBroadcast(intent)

        backupChunks = mutableMapOf()
        receivedChunkIndices = mutableSetOf()
        expectedChunks = 0
        hasStartedSync = false
        currentTransactionId = null
        ignoreUntilStartOrEnd = true
    }

    private fun postTimeout() {
        timeoutOperationCancelled = false // Reset flag before posting
        handler.postDelayed(timeoutRunnable, 30000)
    }

    // Helper function to remove timeout
    private fun removeTimeout() {
        timeoutOperationCancelled = true // Set flag to indicate cancellation intent
        handler.removeCallbacks(timeoutRunnable)
    }

    override fun onDataChanged(dataEvents: DataEventBuffer) {
        try {
            // Collect events first to avoid multiple iterations
            val eventsList = mutableListOf<com.google.android.gms.wearable.DataEvent>()
            dataEvents.forEach { eventsList.add(it) }
            
            // Process sync handshake messages first
            eventsList.forEach { dataEvent ->
                val uri = dataEvent.dataItem.uri
                when (uri.path) {
                    SYNC_ACK_PATH -> {
                        val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                        val transactionId = dataMap.getString("transactionId")
                        if (transactionId != null) {
                            Log.d("DataLayerSync", "Received SYNC_ACK for transaction: $transactionId")
                            com.gabstra.myworkoutassistant.data.SyncHandshakeManager.completeAck(transactionId)
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
                            com.gabstra.myworkoutassistant.data.SyncHandshakeManager.completeCompletion(transactionId)
                            Log.d("DataLayerSync", "Completed completion waiter for transaction: $transactionId")
                            // Show success toast
                            scope.launch(Dispatchers.Main) {
                                Toast.makeText(
                                    context,
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
                            com.gabstra.myworkoutassistant.data.SyncHandshakeManager.completeError(transactionId, errorMessage)
                        } else {
                            Log.w("DataLayerSync", "Received SYNC_ERROR without transactionId, error: $errorMessage")
                        }
                    }
                }
            }
            
            // Process other data events
            eventsList.forEach { dataEvent ->
                val uri = dataEvent.dataItem.uri
                when (uri.path) {
                    SYNC_REQUEST_PATH -> {
                        val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                        val transactionId = dataMap.getString("transactionId")
                        
                        if (transactionId != null) {
                            Log.d("DataLayerSync", "Received SYNC_REQUEST for transaction: $transactionId")
                            
                            scope.launch(Dispatchers.IO) {
                                try {
                                    // Send acknowledgment
                                    val ackDataMapRequest = PutDataMapRequest.create(SYNC_ACK_PATH)
                                    ackDataMapRequest.dataMap.putString("transactionId", transactionId)
                                    ackDataMapRequest.dataMap.putString("timestamp", System.currentTimeMillis().toString())
                                    
                                    val ackRequest = ackDataMapRequest.asPutDataRequest().setUrgent()
                                    val task = dataClient.putDataItem(ackRequest)
                                    Tasks.await(task)
                                    Log.d("DataLayerSync", "Sent sync acknowledgment for transaction: $transactionId")
                                } catch (exception: Exception) {
                                    Log.e("DataLayerSync", "Error sending sync acknowledgment for transaction: $transactionId", exception)
                                    exception.printStackTrace()
                                }
                            }
                        } else {
                            Log.w("DataLayerSync", "Received SYNC_REQUEST without transactionId")
                        }
                    }

                    WORKOUT_STORE_PATH -> {
                        val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                        val compressedJson = dataMap.getByteArray("compressedJson")
                        val transactionId = dataMap.getString("transactionId")
                        
                        scope.launch(Dispatchers.IO) {
                            try {
                                val workoutStoreJson = decompressToString(compressedJson!!)
                                workoutStoreRepository.saveWorkoutStoreFromJson(workoutStoreJson)
                                val intent = Intent(INTENT_ID).apply {
                                    putExtra(WORKOUT_STORE_JSON, workoutStoreJson)
                                    setPackage(packageName)
                                }
                                sendBroadcast(intent)
                                
                                // Send completion acknowledgment
                                transactionId?.let { tid ->
                                    try {
                                        Log.d("DataLayerSync", "Preparing to send SYNC_COMPLETE for transaction: $tid (workout store processed)")
                                        val completeDataMapRequest = PutDataMapRequest.create(SYNC_COMPLETE_PATH)
                                        completeDataMapRequest.dataMap.putString("transactionId", tid)
                                        val timestamp = System.currentTimeMillis().toString()
                                        completeDataMapRequest.dataMap.putString("timestamp", timestamp)
                                        
                                        val completeRequest = completeDataMapRequest.asPutDataRequest().setUrgent()
                                        Log.d("DataLayerSync", "Sending SYNC_COMPLETE for transaction: $tid, timestamp: $timestamp")
                                        val task = dataClient.putDataItem(completeRequest)
                                        Tasks.await(task)
                                        Log.d("DataLayerSync", "Successfully sent SYNC_COMPLETE for transaction: $tid (workout store)")
                                    } catch (exception: Exception) {
                                        Log.e("DataLayerSync", "Failed to send SYNC_COMPLETE for transaction: $tid", exception)
                                    }
                                }
                            } catch (exception: Exception) {
                                Log.e("DataLayerSync", "Error processing workout store", exception)
                                exception.printStackTrace()
                                
                                // Send error response back to sender
                                transactionId?.let { tid ->
                                    try {
                                        Log.e("DataLayerSync", "Sending SYNC_ERROR for transaction: $tid due to processing error")
                                        val errorMessage = exception.message ?: "Unknown error processing workout store"
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

                    BACKUP_CHUNK_PATH -> {
                        val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap

                        val isStart = dataMap.getBoolean("isStart", false)
                        val isLastChunk = dataMap.getBoolean("isLastChunk", false)
                        val backupChunk = dataMap.getByteArray("chunk")
                        val transactionId = dataMap.getString("transactionId")
                        val isRetry = dataMap.getBoolean("isRetry", false)
                        val isLastRetryChunk = dataMap.getBoolean("isLastRetryChunk", false)
                        val chunkIndex = if (dataMap.containsKey("chunkIndex")) dataMap.getInt("chunkIndex", -1) else -1

                        // Retry chunks with same transaction ID should not trigger shouldStop
                        val shouldStop = !isRetry && (
                                (isStart && hasStartedSync) ||
                                (backupChunk != null && !hasStartedSync) ||
                                (currentTransactionId != null && currentTransactionId != transactionId)
                        )

                        Log.d("DataLayerListenerService", "ignoreUntilStartOrEnd: $ignoreUntilStartOrEnd hasBackupChunk: ${backupChunk != null} isStart: $isStart isLastChunk: $isLastChunk isRetry: $isRetry chunkIndex: $chunkIndex transactionId: $transactionId shouldStop: $shouldStop")

                        if (!ignoreUntilStartOrEnd && shouldStop && !isRetry) {
                            removeTimeout()
                            val intent = Intent(INTENT_ID).apply {
                                putExtra(APP_BACKUP_FAILED, APP_BACKUP_FAILED)
                                setPackage(packageName)
                            }

                            sendBroadcast(intent)

                            backupChunks = mutableMapOf()
                            receivedChunkIndices = mutableSetOf()
                            expectedChunks = 0
                            hasStartedSync = false
                            currentTransactionId = null

                            ignoreUntilStartOrEnd = true
                            return
                        }

                        if (isStart) {
                            if (dataMap.containsKey("chunksCount")) {
                                expectedChunks = dataMap.getInt("chunksCount", 0)
                            }

                            Log.d("DataLayerSync", "Backup started with expected chunks: $expectedChunks, transactionId: $transactionId")

                            backupChunks = mutableMapOf()
                            receivedChunkIndices = mutableSetOf()
                            hasStartedSync = true
                            ignoreUntilStartOrEnd = false
                            currentTransactionId = transactionId

                            // Send backup start broadcast (may be duplicate if sync request already triggered it, but that's okay)
                            val intent = Intent(INTENT_ID).apply {
                                putExtra(APP_BACKUP_START_JSON, APP_BACKUP_START_JSON)
                            }.apply { setPackage(packageName) }
                            sendBroadcast(intent)

                            removeTimeout()
                        }

                        if (backupChunk != null && (!ignoreUntilStartOrEnd || isRetry)) {
                            // Extend timeout for retry chunks or regular chunks
                            removeTimeout()
                            postTimeout()

                            // Handle chunk with index
                            if (chunkIndex >= 0) {
                                val currentChunks = backupChunks.toMutableMap()
                                currentChunks[chunkIndex] = backupChunk
                                backupChunks = currentChunks

                                val currentIndices = receivedChunkIndices.toMutableSet()
                                currentIndices.add(chunkIndex)
                                receivedChunkIndices = currentIndices

                                Log.d("DataLayerSync", "Received chunk at index $chunkIndex. Total chunks: ${backupChunks.size}, expected: $expectedChunks, isRetry: $isRetry")
                            } else {
                                // Fallback for backwards compatibility - should not happen with new implementation
                                Log.w("DataLayerSync", "Received chunk without index! Falling back to append behavior.")
                                val currentChunks = backupChunks.toMutableMap()
                                val nextIndex = currentChunks.keys.maxOrNull()?.plus(1) ?: 0
                                currentChunks[nextIndex] = backupChunk
                                backupChunks = currentChunks

                                val currentIndices = receivedChunkIndices.toMutableSet()
                                currentIndices.add(nextIndex)
                                receivedChunkIndices = currentIndices
                            }

                            val progress = receivedChunkIndices.size.toFloat() / expectedChunks

                            val progressIntent = Intent(INTENT_ID).apply {
                                putExtra(APP_BACKUP_PROGRESS_UPDATE, "$progress")
                            }.apply { setPackage(packageName) }
                            sendBroadcast(progressIntent)
                        }

                        if (isLastChunk || isLastRetryChunk) {
                            Log.d("DataLayerSync", "Received last backup chunk (isLastChunk: $isLastChunk, isLastRetryChunk: $isLastRetryChunk). Total chunks received: ${backupChunks.size}, expected: $expectedChunks")
                            if (!ignoreUntilStartOrEnd) {
                                removeTimeout()
                                
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
                                            Log.e("DataLayerSync", "Validation failed: Missing chunks. Expected: $expectedChunks, Received: ${backupChunks.size}, Missing indices: $missingIndices")
                                            
                                            // Send SYNC_ERROR with missing chunk information
                                            transactionId?.let { tid ->
                                                try {
                                                    val errorMessage = "MISSING_CHUNKS: Expected $expectedChunks chunks, received ${backupChunks.size}. Missing indices: $missingIndices"
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
                                            // Don't send APP_BACKUP_FAILED - keep syncing screen visible for retry
                                            return@launch
                                        }
                                        
                                        // All chunks present - proceed with processing
                                        processingStep = "combining chunks"
                                        Log.d("DataLayerSync", "All chunks validated. Combining ${backupChunks.size} chunks for transaction: $transactionId")
                                        
                                        // Combine chunks in index order
                                        val sortedChunks = (0 until expectedChunks).mapNotNull { index ->
                                            backupChunks[index]
                                        }
                                        
                                        if (sortedChunks.size != expectedChunks) {
                                            throw IllegalStateException("Expected $expectedChunks chunks but only ${sortedChunks.size} found after validation")
                                        }
                                        
                                        val backupData = combineChunks(sortedChunks)
                                        
                                        processingStep = "decompressing backup data"
                                        Log.d("DataLayerSync", "Decompressing backup data (size: ${backupData.size} bytes) for transaction: $transactionId")
                                        val jsonBackup = decompressToString(backupData)
                                        
                                        processingStep = "parsing JSON backup"
                                        Log.d("DataLayerSync", "Parsing JSON backup (length: ${jsonBackup.length} chars) for transaction: $transactionId")
                                        val appBackup = fromJSONtoAppBackup(jsonBackup)
                                        
                                        processingStep = "saving workout store"
                                        Log.d("DataLayerSync", "Saving workout store for transaction: $transactionId")
                                        workoutStoreRepository.saveWorkoutStore(appBackup.WorkoutStore)

                                        processingStep = "database operations"
                                        runBlocking {
                                            val allSchedules = workoutScheduleDao.getAllSchedules()

                                            val scheduler = WorkoutAlarmScheduler(context)
                                            for (schedule in allSchedules) {
                                                scheduler.cancelSchedule(schedule)
                                            }

                                            // Wrap database operations in NonCancellable to ensure they complete even if service is destroyed
                                            withContext(NonCancellable) {
                                                workoutScheduleDao.deleteAll()
                                                exerciseSessionProgressionDao.deleteAll()

                                                val insertWorkoutHistoriesJob =
                                                    scope.launch(start = CoroutineStart.LAZY) {
                                                        withContext(NonCancellable) {
                                                            workoutHistoryDao.insertAllWithVersionCheck(*appBackup.WorkoutHistories.toTypedArray())
                                                        }
                                                    }

                                                val insertSetHistoriesJob =
                                                    scope.launch(start = CoroutineStart.LAZY) {
                                                        withContext(NonCancellable) {
                                                            setHistoryDao.insertAllWithVersionCheck(*appBackup.SetHistories.toTypedArray())
                                                        }
                                                    }

                                                val insertExerciseInfosJob =
                                                    scope.launch(start = CoroutineStart.LAZY) {
                                                        withContext(NonCancellable) {
                                                            exerciseInfoDao.insertAllWithVersionCheck(*appBackup.ExerciseInfos.toTypedArray())
                                                        }
                                                    }

                                                val insertWorkoutSchedulesJob =
                                                    scope.launch(start = CoroutineStart.LAZY) {
                                                        withContext(NonCancellable) {
                                                            workoutScheduleDao.deleteAll()
                                                            workoutScheduleDao.insertAll(*appBackup.WorkoutSchedules.toTypedArray())
                                                        }
                                                    }

                                                val insertWorkoutRecordsJob =
                                                    scope.launch(start = CoroutineStart.LAZY) {
                                                        withContext(NonCancellable) {
                                                            workoutRecordDao.deleteAll()
                                                            workoutRecordDao.insertAll(*appBackup.WorkoutRecords.toTypedArray())
                                                        }
                                                    }

                                                val insertExerciseSessionProgressionsJob =
                                                    scope.launch(start = CoroutineStart.LAZY) {
                                                        withContext(NonCancellable) {
                                                            val validExerciseSessionProgressions = appBackup.ExerciseSessionProgressions.filter { progression ->
                                                                appBackup.WorkoutHistories.any { it.id == progression.workoutHistoryId }
                                                            }
                                                            exerciseSessionProgressionDao.insertAll(*validExerciseSessionProgressions.toTypedArray())
                                                        }
                                                    }

                                                joinAll(
                                                    insertWorkoutHistoriesJob,
                                                    insertSetHistoriesJob,
                                                    insertExerciseInfosJob,
                                                    insertWorkoutSchedulesJob,
                                                    insertWorkoutRecordsJob,
                                                    insertExerciseSessionProgressionsJob
                                                )

                                                // Clean up workout histories that are no longer needed
                                                cleanupUnusedWorkoutHistories(appBackup.WorkoutStore.workouts, appBackup.WorkoutHistories.map { it.id }.toSet())
                                            }

                                            val intent = Intent(INTENT_ID).apply {
                                                putExtra(APP_BACKUP_END_JSON, APP_BACKUP_END_JSON)
                                                setPackage(packageName)
                                            }
                                            sendBroadcast(intent)
                                            Log.d("DataLayerSync", "Backup completed and broadcast sent for transaction: $transactionId")
                                            if (!MyApplication.isAppInForeground()) {
                                                showSyncCompleteNotification(this@DataLayerListenerService)
                                            }

                                            // Send completion acknowledgment
                                            transactionId?.let { tid ->
                                                try {
                                                    Log.d("DataLayerSync", "Preparing to send SYNC_COMPLETE for transaction: $tid (backup processed)")
                                                    val completeDataMapRequest = PutDataMapRequest.create(SYNC_COMPLETE_PATH)
                                                    completeDataMapRequest.dataMap.putString("transactionId", tid)
                                                    val timestamp = System.currentTimeMillis().toString()
                                                    completeDataMapRequest.dataMap.putString("timestamp", timestamp)
                                                    
                                                    val completeRequest = completeDataMapRequest.asPutDataRequest().setUrgent()
                                                    Log.d("DataLayerSync", "Sending SYNC_COMPLETE for transaction: $tid, timestamp: $timestamp")
                                                    val task = dataClient.putDataItem(completeRequest)
                                                    Tasks.await(task)
                                                    Log.d("DataLayerSync", "Successfully sent SYNC_COMPLETE for transaction: $tid (backup)")
                                                } catch (exception: Exception) {
                                                    Log.e("DataLayerSync", "Failed to send SYNC_COMPLETE for transaction: $tid", exception)
                                                }
                                            }

                                            backupChunks = mutableMapOf()
                                            receivedChunkIndices = mutableSetOf()
                                            expectedChunks = 0
                                            hasStartedSync = false
                                            ignoreUntilStartOrEnd = false
                                            currentTransactionId = null
                                        }
                                    } catch (exception: Exception) {
                                        // Build comprehensive error message
                                        val exceptionClassName = exception.javaClass.simpleName
                                        val exceptionMessage = exception.message
                                        
                                        // Build error message with safe length limit (DataMap has ~100KB limit, but keep errors reasonable)
                                        val fullErrorMessage = when {
                                            exceptionMessage != null && exceptionMessage.isNotEmpty() -> {
                                                "$exceptionClassName at $processingStep: $exceptionMessage"
                                            }
                                            else -> {
                                                "$exceptionClassName at $processingStep: Unknown error processing backup"
                                            }
                                        }
                                        
                                        // Truncate if too long (keep under 1000 chars to be safe, leaving room for other DataMap fields)
                                        val errorMessage = if (fullErrorMessage.length > 1000) {
                                            fullErrorMessage.take(997) + "..."
                                        } else {
                                            fullErrorMessage
                                        }
                                        
                                        Log.e("DataLayerSync", "Error processing backup at step: $processingStep", exception)
                                        Log.e("DataLayerSync", "Exception type: $exceptionClassName, message: $exceptionMessage")
                                        Log.e("DataLayerSync", "Full error message to send: $fullErrorMessage")
                                        Log.e("DataLayerSync", "Truncated error message (if needed): $errorMessage")
                                        exception.printStackTrace()
                                        
                                        // Log additional context for common error types
                                        when (exception) {
                                            is com.google.gson.JsonSyntaxException -> {
                                                Log.e("DataLayerSync", "JSON parsing error - backup data may be corrupted or incompatible")
                                                Log.e("DataLayerSync", "JSON error details: ${exception.cause?.message ?: "No cause available"}")
                                            }
                                            is OutOfMemoryError -> {
                                                Log.e("DataLayerSync", "Out of memory error - backup may be too large for device")
                                                Log.e("DataLayerSync", "Available memory info: maxMemory=${Runtime.getRuntime().maxMemory()}, freeMemory=${Runtime.getRuntime().freeMemory()}")
                                            }
                                            is java.util.zip.DataFormatException -> {
                                                Log.e("DataLayerSync", "Data decompression error - compressed backup data may be corrupted")
                                            }
                                            is NullPointerException -> {
                                                Log.e("DataLayerSync", "NullPointerException - possible missing data in backup")
                                                Log.e("DataLayerSync", "Stack trace may indicate which field was null")
                                            }
                                            is IllegalStateException -> {
                                                Log.e("DataLayerSync", "IllegalStateException - possible state corruption or invalid data")
                                            }
                                        }
                                        
                                        // Send error response back to sender
                                        transactionId?.let { tid ->
                                            try {
                                                Log.e("DataLayerSync", "Sending SYNC_ERROR for transaction: $tid due to backup processing error")
                                                Log.e("DataLayerSync", "Error message being sent: $errorMessage")
                                                val errorDataMapRequest = PutDataMapRequest.create(SYNC_ERROR_PATH)
                                                errorDataMapRequest.dataMap.putString("transactionId", tid)
                                                errorDataMapRequest.dataMap.putString("errorMessage", errorMessage)
                                                errorDataMapRequest.dataMap.putString("timestamp", System.currentTimeMillis().toString())
                                                
                                                val errorRequest = errorDataMapRequest.asPutDataRequest().setUrgent()
                                                val task = dataClient.putDataItem(errorRequest)
                                                Tasks.await(task)
                                                Log.e("DataLayerSync", "Successfully sent SYNC_ERROR for transaction: $tid")
                                                Log.e("DataLayerSync", "Sent error message: $errorMessage")
                                            } catch (sendErrorException: Exception) {
                                                Log.e("DataLayerSync", "Failed to send SYNC_ERROR for transaction: $tid", sendErrorException)
                                                Log.e("DataLayerSync", "Original error was: $errorMessage")
                                            }
                                        }
                                        
                                        // Clean up state and notify UI of failure
                                        backupChunks = mutableMapOf()
                                        receivedChunkIndices = mutableSetOf()
                                        expectedChunks = 0
                                        hasStartedSync = false
                                        ignoreUntilStartOrEnd = false
                                        currentTransactionId = null
                                        
                                        // Send broadcast to reset UI state (dismiss loading screen)
                                        val failedIntent = Intent(INTENT_ID).apply {
                                            putExtra(APP_BACKUP_FAILED, APP_BACKUP_FAILED)
                                            setPackage(packageName)
                                        }
                                        sendBroadcast(failedIntent)
                                        Log.d("DataLayerSync", "Sent APP_BACKUP_FAILED broadcast to reset UI state")
                                    }
                                }
                            }
                        }
                    }

                    CLEAR_ERROR_LOGS_PATH -> {
                        try {
                            val app = applicationContext as? MyApplication
                            app?.clearErrorLogs()
                            Log.d("DataLayerListenerService", "Error logs cleared from Wear OS")
                        } catch (e: Exception) {
                            Log.e("DataLayerListenerService", "Error clearing error logs", e)
                        }
                    }
                }
            }
        } catch (exception: Exception) {
            exception.printStackTrace()
            Log.e("DataLayerListenerService", "Error processing data", exception)
            removeTimeout()
            val intent = Intent(INTENT_ID).apply {
                putExtra(APP_BACKUP_FAILED, APP_BACKUP_FAILED)
                setPackage(packageName)
            }
            sendBroadcast(intent)
            backupChunks = mutableMapOf()
            receivedChunkIndices = mutableSetOf()
            expectedChunks = 0
            hasStartedSync = false
            ignoreUntilStartOrEnd = true
        }
    }

    /**
     * Cleans up workout histories that are no longer needed for plateau detection.
     * Keeps only the most recent 15 workout histories per exercise (same as phone sync logic)
     * plus any workout histories that were just synced.
     */
    private suspend fun cleanupUnusedWorkoutHistories(
        workouts: List<Workout>,
        syncedWorkoutHistoryIds: Set<UUID>
    ) {
        try {
            // Collect all exercises from workouts (including exercises from Supersets)
            val allExercises = workouts.flatMap { workout ->
                workout.workoutComponents.filterIsInstance<Exercise>() +
                workout.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }
            }.distinctBy { it.id }

            // Get all workout histories currently on the watch
            val allWorkoutHistories = workoutHistoryDao.getAllWorkoutHistories()

            // Start with synced workout histories (these are definitely needed)
            val workoutHistoryIdsToKeep = syncedWorkoutHistoryIds.toMutableSet()

            // For each exercise, get set histories and extract workout history IDs
            // Keep the most recent 15 workout histories per exercise (for plateau detection)
            for (exercise in allExercises) {
                val setHistoriesForExercise = setHistoryDao.getSetHistoriesByExerciseId(exercise.id)
                val workoutHistoryIds = setHistoriesForExercise
                    .mapNotNull { it.workoutHistoryId }
                    .distinct()
                
                if (workoutHistoryIds.isNotEmpty()) {
                    // Get workout histories for this exercise and keep the most recent 15
                    val workoutHistoriesForExercise = allWorkoutHistories
                        .filter { it.id in workoutHistoryIds }
                        .sortedByDescending { it.startTime }
                        .take(15)
                    
                    workoutHistoryIdsToKeep.addAll(workoutHistoriesForExercise.map { it.id })
                }
            }

            // Delete workout histories that aren't in the keep set
            val workoutHistoriesToDelete = allWorkoutHistories.filter { it.id !in workoutHistoryIdsToKeep }
            
            for (workoutHistory in workoutHistoriesToDelete) {
                // Delete associated set histories
                setHistoryDao.deleteByWorkoutHistoryId(workoutHistory.id)
                // Delete associated exercise session progressions
                exerciseSessionProgressionDao.deleteByWorkoutHistoryId(workoutHistory.id)
                // Delete the workout history itself
                workoutHistoryDao.deleteById(workoutHistory.id)
            }
            
            if (workoutHistoriesToDelete.isNotEmpty()) {
                Log.d("DataLayerListenerService", "Cleaned up ${workoutHistoriesToDelete.size} unused workout histories")
            }
        } catch (e: Exception) {
            Log.e("DataLayerListenerService", "Error cleaning up unused workout histories", e)
            // Don't throw - cleanup failure shouldn't break the sync
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        scope.cancel()
    }

    companion object {
        private const val WORKOUT_STORE_PATH = "/workoutStore"
        private const val BACKUP_CHUNK_PATH = "/backupChunkPath"
        const val CLEAR_ERROR_LOGS_PATH = "/clearErrorLogs"
        const val ERROR_LOGS_SYNC_PATH = "/errorLogsSync"
        const val INTENT_ID = "com.gabstra.myworkoutassistant.workoutstore"
        const val WORKOUT_STORE_JSON = "workoutStoreJson"
        const val APP_BACKUP_START_JSON = "appBackupStartJson"
        const val APP_BACKUP_END_JSON = "appBackupEndJson"
        const val APP_BACKUP_FAILED = "appBackupFailed"
        const val APP_BACKUP_PROGRESS_UPDATE = "progress_update"
        const val SYNC_REQUEST_PATH = "/syncRequest"
        const val SYNC_ACK_PATH = "/syncAck"
        const val SYNC_COMPLETE_PATH = "/syncComplete"
        const val SYNC_ERROR_PATH = "/syncError"
        const val HANDSHAKE_TIMEOUT_MS = 5000L
        const val COMPLETION_TIMEOUT_MS = 30000L
    }
}
