package com.gabstra.myworkoutassistant

import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.util.Log
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
import com.gabstra.myworkoutassistant.shared.datalayer.DataLayerPaths
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
import com.google.android.gms.wearable.NodeClient
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import kotlin.coroutines.EmptyCoroutineContext
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

    private val appCeh get() = (application as? MyApplication)?.coroutineExceptionHandler ?: EmptyCoroutineContext

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO + appCeh)
    private lateinit var workoutHistoryDao: WorkoutHistoryDao
    private lateinit var setHistoryDao: SetHistoryDao
    private lateinit var exerciseInfoDao: ExerciseInfoDao
    private lateinit var workoutRecordDao: WorkoutRecordDao
    private lateinit var exerciseSessionProgressionDao: ExerciseSessionProgressionDao

    private val sharedPreferences by lazy {
        getSharedPreferences(
            "backup_state",
            Context.MODE_PRIVATE
        )
    }
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
                    "Failed to parse backupChunks from SharedPreferences with Gson: ${e.message}",
                    e
                )
                sharedPreferences.edit { remove("backup_chunks") }
                mutableMapOf()
            }
        }
        set(value) {
            if (value.isEmpty()) {
                sharedPreferences.edit { remove("backup_chunks") }
            } else {
                try {
                    val base64Map =
                        value.mapKeys { it.key.toString() }.mapValues { (_, byteArray) ->
                            Base64.encode(byteArray)
                        }
                    val jsonString = gson.toJson(base64Map)
                    sharedPreferences.edit { putString("backup_chunks", jsonString) }
                } catch (e: Exception) {
                    Log.e(
                        "DataLayerListenerService",
                        "Failed to save backupChunks to SharedPreferences with Gson: ${e.message}",
                        e
                    )
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
                Log.e(
                    "DataLayerListenerService",
                    "Failed to parse receivedChunkIndices: ${e.message}",
                    e
                )
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
                    Log.e(
                        "DataLayerListenerService",
                        "Failed to save receivedChunkIndices: ${e.message}",
                        e
                    )
                }
            }
        }

    private lateinit var workoutScheduleDao: WorkoutScheduleDao

    private lateinit var context: WearableListenerService

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
        
        // Detect service restart and handle incomplete syncs
        detectAndHandleServiceRestart()
    }
    
    /**
     * Detects if the service was restarted during an active sync and handles incomplete syncs.
     * Attempts auto-healing by sending missing chunks error to phone for retry.
     */
    private fun detectAndHandleServiceRestart() {
        val lastServiceStartTime = sharedPreferences.getLong("last_service_start_time", 0L)
        val currentTime = System.currentTimeMillis()
        val serviceRestartThreshold = 5000L // 5 seconds - if last start was more than 5 seconds ago, likely a restart
        
        // Check if there's an incomplete sync
        val hasIncompleteSync = hasStartedSync && currentTransactionId != null
        
        if (hasIncompleteSync && (currentTime - lastServiceStartTime > serviceRestartThreshold)) {
            val transactionId = currentTransactionId
            Log.w(
                "DataLayerSync",
                "Detected service restart during active sync. Transaction: $transactionId. Attempting auto-heal."
            )
            
            // Attempt auto-healing by sending missing chunks error to phone
            scope.launch(Dispatchers.IO) {
                try {
                    // Check connection before attempting recovery
                    val isConnected = checkConnectionDuringSync(transactionId)
                    if (!isConnected) {
                        Log.w(
                            "DataLayerSync",
                            "Connection lost during service restart recovery for transaction: $transactionId. Cleaning up."
                        )
                        // Connection lost - clean up immediately
                        cleanupIncompleteSyncState()
                        return@launch
                    }
                    
                    // Calculate missing chunks
                    val missingIndices = (0 until expectedChunks).filter { it !in receivedChunkIndices }
                    
                    if (missingIndices.isEmpty() && receivedChunkIndices.size == expectedChunks) {
                        // All chunks received but processing may have failed - different error
                        Log.w(
                            "DataLayerSync",
                            "All chunks received but sync incomplete for transaction: $transactionId. May have failed during processing."
                        )
                        // Send generic error to trigger phone retry
                        sendSyncErrorForRecovery(
                            transactionId ?: return@launch,
                            "SYNC_INCOMPLETE: All chunks received but sync did not complete. Transaction: $transactionId"
                        )
                    } else if (missingIndices.isNotEmpty()) {
                        // Missing chunks - send error to trigger phone retry
                        Log.d(
                            "DataLayerSync",
                            "Attempting auto-heal for transaction: $transactionId. Missing ${missingIndices.size} chunks: $missingIndices"
                        )
                        sendMissingChunksError(transactionId ?: return@launch, missingIndices, expectedChunks, receivedChunkIndices.size)
                        postRetryTimeout(maxOf(expectedChunks, 1))
                    } else {
                        // No chunks received yet - request full retry
                        Log.d(
                            "DataLayerSync",
                            "No chunks received yet for transaction: $transactionId. Requesting full retry."
                        )
                        sendSyncErrorForRecovery(
                            transactionId ?: return@launch,
                            "MISSING_CHUNKS: Expected $expectedChunks chunks, received 0. Missing indices: ${(0 until expectedChunks).toList()}"
                        )
                        postRetryTimeout(maxOf(expectedChunks, 1))
                    }
                    
                    // Keep state to allow phone retry - don't clean up yet
                    // State will be cleaned up when:
                    // 1. Phone retries successfully (normal completion)
                    // 2. New sync starts with different transaction ID (handled in onDataChanged)
                    // 3. Connection is lost (handled above)
                } catch (e: Exception) {
                    Log.e(
                        "DataLayerSync",
                        "Error during auto-heal recovery for transaction: $transactionId",
                        e
                    )
                    // If recovery attempt fails, clean up
                    cleanupIncompleteSyncState()
                }
            }
        }
        
        // Update last service start time
        sharedPreferences.edit().putLong("last_service_start_time", currentTime).apply()
    }
    
    /**
     * Cleans up incomplete sync state and notifies UI.
     * This clears sync state when sync fails or times out.
     */
    private fun cleanupIncompleteSyncState() {
        removeTimeout()
        removeRetryTimeout()
        backupChunks = mutableMapOf()
        receivedChunkIndices = mutableSetOf()
        expectedChunks = 0
        hasStartedSync = false
        ignoreUntilStartOrEnd = false
        currentTransactionId = null
        
        // Notify UI that sync was interrupted - this will reset sync state in AppViewModel
        val intent = Intent(INTENT_ID).apply {
            putExtra(APP_BACKUP_FAILED, APP_BACKUP_FAILED)
            setPackage(packageName)
        }
        sendBroadcast(intent)
        Log.d("DataLayerSync", "Cleaned up incomplete sync state and notified UI")
    }
    
    /**
     * Sends SYNC_ERROR with missing chunks information to trigger phone retry.
     */
    private suspend fun sendMissingChunksError(
        transactionId: String,
        missingIndices: List<Int>,
        expectedChunks: Int,
        receivedChunks: Int
    ) {
        val errorMessage = "MISSING_CHUNKS: Expected $expectedChunks chunks, received $receivedChunks. Missing indices: $missingIndices"
        sendSyncErrorForRecovery(transactionId, errorMessage)
    }
    
    /**
     * Sends SYNC_ERROR message to phone for recovery attempt.
     */
    private suspend fun sendSyncErrorForRecovery(transactionId: String, errorMessage: String) {
        try {
            Log.d(
                "DataLayerSync",
                "Sending SYNC_ERROR for auto-heal recovery. Transaction: $transactionId, Error: $errorMessage"
            )
            val errorPath = DataLayerPaths.buildPath(
                DataLayerPaths.SYNC_ERROR_PREFIX,
                transactionId
            )
            val errorDataMapRequest = PutDataMapRequest.create(errorPath)
            errorDataMapRequest.dataMap.putString("transactionId", transactionId)
            errorDataMapRequest.dataMap.putString("errorMessage", errorMessage)
            errorDataMapRequest.dataMap.putString(
                "timestamp",
                System.currentTimeMillis().toString()
            )

            val errorRequest = errorDataMapRequest.asPutDataRequest().setUrgent()
            val task = dataClient.putDataItem(errorRequest)
            Tasks.await(task)
            Log.d(
                "DataLayerSync",
                "Successfully sent SYNC_ERROR for auto-heal recovery. Transaction: $transactionId"
            )
        } catch (e: Exception) {
            Log.e(
                "DataLayerSync",
                "Failed to send SYNC_ERROR for auto-heal recovery. Transaction: $transactionId",
                e
            )
            throw e
        }
    }

    private val handler = Handler(Looper.getMainLooper())

    @Volatile // Ensure visibility across threads
    private var timeoutOperationCancelled = false

    @Volatile
    private var retryTimeoutOperationCancelled = false

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

        removeRetryTimeout()
        backupChunks = mutableMapOf()
        receivedChunkIndices = mutableSetOf()
        expectedChunks = 0
        hasStartedSync = false
        currentTransactionId = null
        ignoreUntilStartOrEnd = true
    }

    private val retryTimeoutRunnable = Runnable {
        if (retryTimeoutOperationCancelled) {
            return@Runnable
        }
        Log.w("DataLayerSync", "Retry timeout triggered - aborting stuck backup sync")
        cleanupIncompleteSyncState()
    }

    private fun postTimeout(chunksCount: Int = expectedChunks) {
        timeoutOperationCancelled = false // Reset flag before posting
        // Use dynamic timeout calculation based on chunk count
        val timeoutMs = if (chunksCount > 0) {
            calculateCompletionTimeout(chunksCount)
        } else {
            // Fallback to default if chunksCount not available yet
            BASE_COMPLETION_TIMEOUT_MS + PER_CHUNK_TIMEOUT_MS
        }
        Log.d("DataLayerSync", "Posting timeout: ${timeoutMs}ms for $chunksCount chunks")
        handler.postDelayed(timeoutRunnable, timeoutMs)
    }

    private fun postRetryTimeout(chunksCount: Int = expectedChunks) {
        retryTimeoutOperationCancelled = false
        val baseTimeout = if (chunksCount > 0) {
            calculateCompletionTimeout(chunksCount)
        } else {
            BASE_COMPLETION_TIMEOUT_MS
        }
        val retryTimeoutMs = minOf(baseTimeout * 2, MAX_COMPLETION_TIMEOUT_MS)
        Log.d("DataLayerSync", "Posting retry timeout: ${retryTimeoutMs}ms for $chunksCount chunks")
        handler.postDelayed(retryTimeoutRunnable, retryTimeoutMs)
    }

    // Helper function to remove timeout
    private fun removeTimeout() {
        timeoutOperationCancelled = true // Set flag to indicate cancellation intent
        handler.removeCallbacks(timeoutRunnable)
    }

    private fun removeRetryTimeout() {
        retryTimeoutOperationCancelled = true
        handler.removeCallbacks(retryTimeoutRunnable)
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

    override fun onDataChanged(dataEvents: DataEventBuffer) {
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
                        transactionId?.let { tid ->
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
                                            "Received stale SYNC_ACK for transaction: $tid (age: ${age}ms, threshold: ${staleAckThreshold}ms) - ignoring"
                                        )
                                        return@forEach
                                    }
                                } catch (e: NumberFormatException) {
                                    Log.w(
                                        "DataLayerSync",
                                        "Received SYNC_ACK with invalid timestamp format for transaction: $tid"
                                    )
                                }
                            }

                            Log.d("DataLayerSync", "Received SYNC_ACK for transaction: $tid")
                            com.gabstra.myworkoutassistant.data.SyncHandshakeManager.completeAck(tid)
                        } ?: Log.w(
                            "DataLayerSync",
                            "Received SYNC_ACK without transactionId - ignoring stale message"
                        )
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
                            Log.d(
                                "WorkoutSync",
                                "SYNC_TRACE event=complete side=wear direction=recv tx=$tid timestamp=$timestamp"
                            )
                            com.gabstra.myworkoutassistant.data.SyncHandshakeManager.completeCompletion(
                                tid
                            )
                            Log.d(
                                "DataLayerSync",
                                "Completed completion waiter for transaction: $tid"
                            )
                            // Send broadcast to MainActivity to handle toast and mark history synced (with syncStatus check)
                            val intent = Intent(INTENT_ID).apply {
                                putExtra(SYNC_COMPLETE, SYNC_COMPLETE)
                                putExtra(TRANSACTION_ID, tid)
                                setPackage(packageName)
                            }
                            sendBroadcast(intent)
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
                            Log.d(
                                "WorkoutSync",
                                "SYNC_TRACE event=error side=wear direction=recv tx=$tid message=$errorMessage"
                            )
                            com.gabstra.myworkoutassistant.data.SyncHandshakeManager.completeError(
                                tid,
                                errorMessage
                            )
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

                        finalTransactionId?.let { tid ->
                            Log.d("DataLayerSync", "Received SYNC_REQUEST for transaction: $tid")

                            scope.launch(Dispatchers.IO) {
                                try {
                                    // Send acknowledgment to transaction-scoped path
                                    val ackPath = DataLayerPaths.buildPath(
                                        DataLayerPaths.SYNC_ACK_PREFIX,
                                        tid
                                    )
                                    val ackDataMapRequest = PutDataMapRequest.create(ackPath)
                                    ackDataMapRequest.dataMap.putString("transactionId", tid)
                                    ackDataMapRequest.dataMap.putString(
                                        "timestamp",
                                        System.currentTimeMillis().toString()
                                    )

                                    val ackRequest =
                                        ackDataMapRequest.asPutDataRequest().setUrgent()
                                    val task = dataClient.putDataItem(ackRequest)
                                    Tasks.await(task)
                                    Log.d(
                                        "DataLayerSync",
                                        "Sent sync acknowledgment for transaction: $tid"
                                    )
                                } catch (exception: Exception) {
                                    Log.e(
                                        "DataLayerSync",
                                        "Error sending sync acknowledgment for transaction: $tid",
                                        exception
                                    )
                                    exception.printStackTrace()
                                }
                            }
                        } ?: Log.w("DataLayerSync", "Received SYNC_REQUEST without transactionId")
                    }

                    // Handle transaction-scoped workout store path
                    DataLayerPaths.matchesPrefix(path, DataLayerPaths.WORKOUT_STORE_PREFIX) -> {
                        val transactionId = DataLayerPaths.parseTransactionId(
                            path,
                            DataLayerPaths.WORKOUT_STORE_PREFIX
                        )
                        val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                        val compressedJson = dataMap.getByteArray("compressedJson")
                        // Fallback to DataMap if path parsing fails
                        val finalTransactionId = transactionId ?: dataMap.getString("transactionId")

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
                                finalTransactionId?.let { tid ->
                                    try {
                                        Log.d(
                                            "DataLayerSync",
                                            "Preparing to send SYNC_COMPLETE for transaction: $tid (workout store processed)"
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
                                            "Successfully sent SYNC_COMPLETE for transaction: $tid (workout store)"
                                        )
                                    } catch (exception: Exception) {
                                        Log.e(
                                            "DataLayerSync",
                                            "Failed to send SYNC_COMPLETE for transaction: $tid",
                                            exception
                                        )
                                    }
                                }
                            } catch (exception: Exception) {
                                Log.e("DataLayerSync", "Error processing workout store", exception)
                                exception.printStackTrace()

                                // Send error response back to sender
                                finalTransactionId?.let { tid ->
                                    try {
                                        Log.e(
                                            "DataLayerSync",
                                            "Sending SYNC_ERROR for transaction: $tid due to processing error"
                                        )
                                        val errorMessage = exception.message
                                            ?: "Unknown error processing workout store"
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

                    // Handle transaction-scoped backup paths
                    DataLayerPaths.matchesPrefix(path, DataLayerPaths.APP_BACKUP_START_PREFIX) ||
                            DataLayerPaths.matchesPrefix(
                                path,
                                DataLayerPaths.APP_BACKUP_CHUNK_PREFIX
                            ) -> {
                        val isStartPath = DataLayerPaths.matchesPrefix(
                            path,
                            DataLayerPaths.APP_BACKUP_START_PREFIX
                        )
                        val isChunkPath = DataLayerPaths.matchesPrefix(
                            path,
                            DataLayerPaths.APP_BACKUP_CHUNK_PREFIX
                        )

                        if (isStartPath || isChunkPath) {
                            val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap

                            // Parse transactionId from path
                            val transactionIdFromPath = if (isStartPath) {
                                DataLayerPaths.parseTransactionId(
                                    path,
                                    DataLayerPaths.APP_BACKUP_START_PREFIX
                                )
                            } else {
                                DataLayerPaths.parseTransactionId(
                                    path,
                                    DataLayerPaths.APP_BACKUP_CHUNK_PREFIX
                                )
                            }

                            // Parse chunkIndex from path (if chunk path)
                            val chunkIndexFromPath = if (isChunkPath) {
                                DataLayerPaths.parseChunkIndex(
                                    path,
                                    DataLayerPaths.APP_BACKUP_CHUNK_PREFIX
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
                            val backupChunk = dataMap.getByteArray("chunk")
                            val isRetry = dataMap.getBoolean("isRetry", false)
                            val isLastRetryChunk = dataMap.getBoolean("isLastRetryChunk", false)

                            // Retry chunks with same transaction ID should not trigger shouldStop
                            val shouldStop = !isRetry && (
                                    (isStart && hasStartedSync) ||
                                            (backupChunk != null && !hasStartedSync) ||
                                            (currentTransactionId != null && currentTransactionId != transactionId)
                                    )

                            Log.d(
                                "DataLayerListenerService",
                                "ignoreUntilStartOrEnd: $ignoreUntilStartOrEnd hasBackupChunk: ${backupChunk != null} isStart: $isStart isLastChunk: $isLastChunk isRetry: $isRetry chunkIndex: $chunkIndex transactionId: $transactionId shouldStop: $shouldStop"
                            )

                            if (!ignoreUntilStartOrEnd && shouldStop && !isRetry) {
                                removeTimeout()
                                removeRetryTimeout()
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

                                // If starting a new sync with different transaction ID, clean up old incomplete sync
                                if (hasStartedSync && currentTransactionId != null && currentTransactionId != transactionId) {
                                    Log.d(
                                    "DataLayerSync",
                                    "New sync starting with transaction: $transactionId. Cleaning up old incomplete sync: $currentTransactionId"
                                )
                                // Clean up old incomplete sync state
                                removeTimeout()
                                removeRetryTimeout()
                                backupChunks = mutableMapOf()
                                receivedChunkIndices = mutableSetOf()
                                expectedChunks = 0
                                }

                                Log.d(
                                    "DataLayerSync",
                                    "Backup started with expected chunks: $expectedChunks, transactionId: $transactionId"
                                )

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
                                removeRetryTimeout()
                                // Post initial timeout based on expected chunks (fallback to 1)
                                postTimeout(maxOf(expectedChunks, 1))
                            }

                            if (backupChunk != null && (!ignoreUntilStartOrEnd || isRetry)) {
                                // Extend timeout dynamically based on remaining chunks
                                removeTimeout()
                                val remainingChunks = expectedChunks - receivedChunkIndices.size
                                postTimeout(maxOf(remainingChunks, 1)) // At least 1 to ensure timeout is set
                                if (isRetry) {
                                    removeRetryTimeout()
                                    postRetryTimeout(maxOf(expectedChunks, 1))
                                }

                                // Handle chunk with index
                                if (chunkIndex >= 0) {
                                    val currentChunks = backupChunks.toMutableMap()
                                    currentChunks[chunkIndex] = backupChunk
                                    backupChunks = currentChunks

                                    val currentIndices = receivedChunkIndices.toMutableSet()
                                    currentIndices.add(chunkIndex)
                                    receivedChunkIndices = currentIndices

                                    Log.d(
                                        "DataLayerSync",
                                        "Received chunk at index $chunkIndex. Total chunks: ${backupChunks.size}, expected: $expectedChunks, isRetry: $isRetry"
                                    )
                                } else {
                                    // Fallback for backwards compatibility - should not happen with new implementation
                                    Log.w(
                                        "DataLayerSync",
                                        "Received chunk without index! Falling back to append behavior."
                                    )
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
                                Log.d(
                                    "DataLayerSync",
                                    "Received last backup chunk (isLastChunk: $isLastChunk, isLastRetryChunk: $isLastRetryChunk). Total chunks received: ${backupChunks.size}, expected: $expectedChunks"
                                )
                                if (!ignoreUntilStartOrEnd) {
                                    removeTimeout()

                                    scope.launch(Dispatchers.IO) {
                                        var processingStep = "initialization"
                                        try {
                                            processingStep = "validating chunks"
                                            
                                            // Log chunk reception details
                                            val chunkReceptionStartTime = System.currentTimeMillis()
                                            val receivedIndicesList = receivedChunkIndices.sorted()
                                            Log.d(
                                                "DataLayerSync",
                                                "Chunk validation for transaction: $transactionId - Expected: $expectedChunks, Received: ${backupChunks.size}, Received indices: $receivedIndicesList"
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
                                                    "Validation failed: Missing chunks. Expected: $expectedChunks, Received: ${backupChunks.size}, Missing indices: $missingIndices, Validation time: ${validationTime}ms"
                                                )
                                                // Log chunk delivery metrics
                                                val deliveryRate = (backupChunks.size.toFloat() / expectedChunks * 100).toInt()
                                                Log.e(
                                                    "DataLayerSync",
                                                    "Chunk delivery metrics - Delivery rate: $deliveryRate%, Missing: ${missingIndices.size}, Transaction: $transactionId"
                                                )

                                                // Send SYNC_ERROR with missing chunk information
                                                transactionId?.let { tid ->
                                                    try {
                                                        val errorMessage =
                                                            "MISSING_CHUNKS: Expected $expectedChunks chunks, received ${backupChunks.size}. Missing indices: $missingIndices"
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
                                                // Don't send APP_BACKUP_FAILED - keep syncing screen visible for retry
                                                removeRetryTimeout()
                                                postRetryTimeout(maxOf(expectedChunks, 1))
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
                                                "All chunks validated. Combining ${backupChunks.size} chunks for transaction: $transactionId"
                                            )

                                            // Combine chunks in index order
                                            val sortedChunks =
                                                (0 until expectedChunks).mapNotNull { index ->
                                                    backupChunks[index]
                                                }

                                            if (sortedChunks.size != expectedChunks) {
                                                throw IllegalStateException("Expected $expectedChunks chunks but only ${sortedChunks.size} found after validation")
                                            }

                                            val backupData = combineChunks(sortedChunks)

                                            processingStep = "decompressing backup data"
                                            Log.d(
                                                "DataLayerSync",
                                                "Decompressing backup data (size: ${backupData.size} bytes) for transaction: $transactionId"
                                            )
                                            val jsonBackup = decompressToString(backupData)

                                            processingStep = "parsing JSON backup"
                                            Log.d(
                                                "DataLayerSync",
                                                "Parsing JSON backup (length: ${jsonBackup.length} chars) for transaction: $transactionId"
                                            )
                                            val appBackup = fromJSONtoAppBackup(jsonBackup)

                                            processingStep = "saving workout store"
                                            Log.d(
                                                "DataLayerSync",
                                                "Saving workout store for transaction: $transactionId"
                                            )
                                            workoutStoreRepository.saveWorkoutStore(appBackup.WorkoutStore)

                                            processingStep = "database operations"
                                            runBlocking {
                                                val allSchedules =
                                                    workoutScheduleDao.getAllSchedules()

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
                                                                workoutHistoryDao.insertAllWithVersionCheck(
                                                                    *appBackup.WorkoutHistories.toTypedArray()
                                                                )
                                                            }
                                                        }

                                                    val insertSetHistoriesJob =
                                                        scope.launch(start = CoroutineStart.LAZY) {
                                                            withContext(NonCancellable) {
                                                                setHistoryDao.insertAllWithVersionCheck(
                                                                    *appBackup.SetHistories.toTypedArray()
                                                                )
                                                            }
                                                        }

                                                    val insertExerciseInfosJob =
                                                        scope.launch(start = CoroutineStart.LAZY) {
                                                            withContext(NonCancellable) {
                                                                exerciseInfoDao.insertAllWithVersionCheck(
                                                                    *appBackup.ExerciseInfos.toTypedArray()
                                                                )
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
                                                                val validExerciseSessionProgressions =
                                                                    appBackup.ExerciseSessionProgressions.filter { progression ->
                                                                        appBackup.WorkoutHistories.any { it.id == progression.workoutHistoryId }
                                                                    }
                                                                exerciseSessionProgressionDao.insertAll(
                                                                    *validExerciseSessionProgressions.toTypedArray()
                                                                )
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
                                                    cleanupUnusedWorkoutHistories(
                                                        appBackup.WorkoutStore.workouts,
                                                        appBackup.WorkoutHistories.map { it.id }
                                                            .toSet()
                                                    )
                                                }

                                                val intent = Intent(INTENT_ID).apply {
                                                    putExtra(
                                                        APP_BACKUP_END_JSON,
                                                        APP_BACKUP_END_JSON
                                                    )
                                                    setPackage(packageName)
                                                }
                                                sendBroadcast(intent)
                                                Log.d(
                                                    "DataLayerSync",
                                                    "Backup completed and broadcast sent for transaction: $transactionId"
                                                )
                                                if (!MyApplication.isAppInForeground()) {
                                                    showSyncCompleteNotification(this@DataLayerListenerService)
                                                }

                                                // Send completion acknowledgment
                                                transactionId?.let { tid ->
                                                    try {
                                                        Log.d(
                                                            "DataLayerSync",
                                                            "Preparing to send SYNC_COMPLETE for transaction: $tid (backup processed)"
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
                                                            "Successfully sent SYNC_COMPLETE for transaction: $tid (backup)"
                                                        )
                                                    } catch (exception: Exception) {
                                                        Log.e(
                                                            "DataLayerSync",
                                                            "Failed to send SYNC_COMPLETE for transaction: $tid",
                                                            exception
                                                        )
                                                    }
                                                }

                                                backupChunks = mutableMapOf()
                                                receivedChunkIndices = mutableSetOf()
                                                expectedChunks = 0
                                                hasStartedSync = false
                                                ignoreUntilStartOrEnd = false
                                                currentTransactionId = null
                                                removeRetryTimeout()
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

                                            Log.e(
                                                "DataLayerSync",
                                                "Error processing backup at step: $processingStep",
                                                exception
                                            )
                                            Log.e(
                                                "DataLayerSync",
                                                "Exception type: $exceptionClassName, message: $exceptionMessage"
                                            )
                                            Log.e(
                                                "DataLayerSync",
                                                "Full error message to send: $fullErrorMessage"
                                            )
                                            Log.e(
                                                "DataLayerSync",
                                                "Truncated error message (if needed): $errorMessage"
                                            )
                                            exception.printStackTrace()

                                            // Log additional context for common error types
                                            when (exception) {
                                                is com.google.gson.JsonSyntaxException -> {
                                                    Log.e(
                                                        "DataLayerSync",
                                                        "JSON parsing error - backup data may be corrupted or incompatible"
                                                    )
                                                    Log.e(
                                                        "DataLayerSync",
                                                        "JSON error details: ${exception.cause?.message ?: "No cause available"}"
                                                    )
                                                }

                                                is OutOfMemoryError -> {
                                                    Log.e(
                                                        "DataLayerSync",
                                                        "Out of memory error - backup may be too large for device"
                                                    )
                                                    Log.e(
                                                        "DataLayerSync",
                                                        "Available memory info: maxMemory=${
                                                            Runtime.getRuntime().maxMemory()
                                                        }, freeMemory=${
                                                            Runtime.getRuntime().freeMemory()
                                                        }"
                                                    )
                                                }

                                                is java.util.zip.DataFormatException -> {
                                                    Log.e(
                                                        "DataLayerSync",
                                                        "Data decompression error - compressed backup data may be corrupted"
                                                    )
                                                }

                                                is NullPointerException -> {
                                                    Log.e(
                                                        "DataLayerSync",
                                                        "NullPointerException - possible missing data in backup"
                                                    )
                                                    Log.e(
                                                        "DataLayerSync",
                                                        "Stack trace may indicate which field was null"
                                                    )
                                                }

                                                is IllegalStateException -> {
                                                    Log.e(
                                                        "DataLayerSync",
                                                        "IllegalStateException - possible state corruption or invalid data"
                                                    )
                                                }
                                            }

                                            // Send error response back to sender
                                            transactionId?.let { tid ->
                                                try {
                                                    Log.e(
                                                        "DataLayerSync",
                                                        "Sending SYNC_ERROR for transaction: $tid due to backup processing error"
                                                    )
                                                    Log.e(
                                                        "DataLayerSync",
                                                        "Error message being sent: $errorMessage"
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
                                                    Log.e(
                                                        "DataLayerSync",
                                                        "Sent error message: $errorMessage"
                                                    )
                                                } catch (sendErrorException: Exception) {
                                                    Log.e(
                                                        "DataLayerSync",
                                                        "Failed to send SYNC_ERROR for transaction: $tid",
                                                        sendErrorException
                                                    )
                                                    Log.e(
                                                        "DataLayerSync",
                                                        "Original error was: $errorMessage"
                                                    )
                                                }
                                            }

                                            // Clean up state and notify UI of failure
                                            removeRetryTimeout()
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
                                            Log.d(
                                                "DataLayerSync",
                                                "Sent APP_BACKUP_FAILED broadcast to reset UI state"
                                            )
                                        }
                                    }
                                }
                            }
                        } // End of backup path handling
                    }

                    path == CLEAR_ERROR_LOGS_PATH -> {
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
            removeRetryTimeout()
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
                        workout.workoutComponents.filterIsInstance<Superset>()
                            .flatMap { it.exercises }
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
            val workoutHistoriesToDelete =
                allWorkoutHistories.filter { it.id !in workoutHistoryIdsToKeep }

            for (workoutHistory in workoutHistoriesToDelete) {
                // Delete associated set histories
                setHistoryDao.deleteByWorkoutHistoryId(workoutHistory.id)
                // Delete associated exercise session progressions
                exerciseSessionProgressionDao.deleteByWorkoutHistoryId(workoutHistory.id)
                // Delete the workout history itself
                workoutHistoryDao.deleteById(workoutHistory.id)
            }

            if (workoutHistoriesToDelete.isNotEmpty()) {
                Log.d(
                    "DataLayerListenerService",
                    "Cleaned up ${workoutHistoriesToDelete.size} unused workout histories"
                )
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
        const val CLEAR_ERROR_LOGS_PATH = "/clearErrorLogs"
        const val ERROR_LOGS_SYNC_PATH = "/errorLogsSync"
        const val INTENT_ID = "com.gabstra.myworkoutassistant.workoutstore"
        const val WORKOUT_STORE_JSON = "workoutStoreJson"
        const val APP_BACKUP_START_JSON = "appBackupStartJson"
        const val APP_BACKUP_END_JSON = "appBackupEndJson"
        const val APP_BACKUP_FAILED = "appBackupFailed"
        const val APP_BACKUP_PROGRESS_UPDATE = "progress_update"
        const val SYNC_COMPLETE = "syncComplete"
        const val TRANSACTION_ID = "transactionId"
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
