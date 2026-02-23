package com.gabstra.myworkoutassistant

import android.annotation.SuppressLint
import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.net.Uri
import android.os.Environment
import android.provider.MediaStore
import android.util.Log
import android.widget.Toast
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.RestingHeartRateRecord
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.TotalCaloriesBurnedRecord
import androidx.health.connect.client.records.metadata.Device
import androidx.health.connect.client.records.metadata.Metadata
import androidx.health.connect.client.units.Energy
import com.gabstra.myworkoutassistant.composables.FilterRange
import com.gabstra.myworkoutassistant.shared.AppBackup
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.ExerciseInfo
import com.gabstra.myworkoutassistant.shared.ExerciseInfoDao
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgression
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgressionDao
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutPlan
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.compressString
import com.gabstra.myworkoutassistant.shared.datalayer.DataLayerPaths
import com.gabstra.myworkoutassistant.shared.equipments.AccessoryEquipment
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.export.equipmentToJSON
import com.gabstra.myworkoutassistant.shared.export.extractEquipmentFromWorkoutPlan
import com.gabstra.myworkoutassistant.shared.export.ExerciseHistoryMarkdownResult
import com.gabstra.myworkoutassistant.shared.export.buildExerciseHistoryMarkdown
import com.gabstra.myworkoutassistant.shared.export.buildWorkoutPlanMarkdown
import com.gabstra.myworkoutassistant.shared.fromAppBackupToJSON
import com.gabstra.myworkoutassistant.shared.fromAppBackupToJSONPrettyPrint
import com.gabstra.myworkoutassistant.shared.fromJSONtoAppBackup
import com.gabstra.myworkoutassistant.shared.fromWorkoutStoreToJSON
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.utils.DoubleProgressionHelper
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
import com.gabstra.myworkoutassistant.shared.utils.Ternary
import com.gabstra.myworkoutassistant.shared.utils.compareSetListsUnordered
import com.gabstra.myworkoutassistant.shared.viewmodels.ProgressionState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import com.google.android.gms.tasks.Tasks
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.PutDataMapRequest
import com.google.android.gms.wearable.Wearable
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.selects.select
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.coroutines.CancellationException
import java.text.SimpleDateFormat
import java.time.DayOfWeek
import java.time.Duration
import java.time.Instant
import java.time.LocalDate
import java.time.YearMonth
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.temporal.TemporalAdjusters
import java.util.Date
import java.util.Locale
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import kotlin.math.pow
import kotlin.math.roundToInt
import java.security.MessageDigest

/**
 * Specific error types for sync operations to improve error handling and debugging.
 */
sealed class SyncError(message: String, val transactionId: String? = null, val retryAttempt: Int = 0) : Exception(message) {
    class ConnectionError(transactionId: String?, retryAttempt: Int = 0) : 
        SyncError("No connection available - devices are not connected", transactionId, retryAttempt)
    
    class TimeoutError(transactionId: String?, val timeoutMs: Long, retryAttempt: Int = 0) : 
        SyncError("Sync timed out after ${timeoutMs}ms", transactionId, retryAttempt)
    
    class ChunkError(transactionId: String?, val missingIndices: List<Int>, val expected: Int, val received: Int, retryAttempt: Int = 0) : 
        SyncError("Missing chunks: expected $expected, received $received. Missing indices: $missingIndices", transactionId, retryAttempt)
    
    class ProcessingError(transactionId: String?, val step: String, cause: Throwable, retryAttempt: Int = 0) : 
        SyncError("Error at $step: ${cause.message}", transactionId, retryAttempt) {
            init {
                initCause(cause)
            }
        }
    
    class HandshakeError(transactionId: String?, retryAttempt: Int = 0) : 
        SyncError("Handshake failed - unable to establish connection", transactionId, retryAttempt)
}

// Helper object to manage sync handshake state
object SyncHandshakeManager {
    private val pendingAcks = ConcurrentHashMap<String, CompletableDeferred<Unit>>()
    private val pendingCompletions = ConcurrentHashMap<String, CompletableDeferred<Unit>>()
    private val pendingErrors = ConcurrentHashMap<String, CompletableDeferred<String>>()
    private val completedCompletions = ConcurrentHashMap.newKeySet<String>()
    private val completedErrors = ConcurrentHashMap<String, String>()

    fun registerAckWaiter(transactionId: String): CompletableDeferred<Unit> {
        val deferred = CompletableDeferred<Unit>()
        pendingAcks[transactionId] = deferred
        return deferred
    }

    fun registerCompletionWaiter(transactionId: String): CompletableDeferred<Unit> {
        if (completedCompletions.remove(transactionId)) {
            return CompletableDeferred<Unit>().apply { complete(Unit) }
        }
        return pendingCompletions.compute(transactionId) { _, existing ->
            when {
                existing == null -> CompletableDeferred<Unit>()
                existing.isCancelled -> CompletableDeferred<Unit>()
                else -> existing
            }
        } ?: CompletableDeferred<Unit>()
    }

    fun registerErrorWaiter(transactionId: String): CompletableDeferred<String> {
        val completedError = completedErrors.remove(transactionId)
        if (completedError != null) {
            return CompletableDeferred<String>().apply { complete(completedError) }
        }
        return pendingErrors.compute(transactionId) { _, existing ->
            when {
                existing == null -> CompletableDeferred<String>()
                existing.isCancelled -> CompletableDeferred<String>()
                else -> existing
            }
        } ?: CompletableDeferred<String>()
    }
    
    fun hasError(transactionId: String): Boolean {
        if (completedErrors.containsKey(transactionId)) return true
        val deferred = pendingErrors[transactionId]
        return deferred?.isCompleted == true
    }

    fun completeAck(transactionId: String) {
        pendingAcks.remove(transactionId)?.complete(Unit)
    }

    fun completeCompletion(transactionId: String) {
        completedCompletions.add(transactionId)
        pendingCompletions[transactionId]?.let {
            if (!it.isCompleted) {
                it.complete(Unit)
            }
        }
    }

    fun hasCompletion(transactionId: String): Boolean {
        if (completedCompletions.contains(transactionId)) return true
        val deferred = pendingCompletions[transactionId]
        return deferred?.isCompleted == true
    }

    fun completeError(transactionId: String, errorMessage: String) {
        completedErrors[transactionId] = errorMessage
        pendingErrors[transactionId]?.let {
            if (!it.isCompleted) {
                it.complete(errorMessage)
            }
        }
    }

    fun cleanup(transactionId: String) {
        pendingAcks.remove(transactionId)?.cancel()
        pendingCompletions.remove(transactionId)?.cancel()
        pendingErrors.remove(transactionId)?.cancel()
        completedCompletions.remove(transactionId)
        completedErrors.remove(transactionId)
    }
}

/**
 * Checks if at least one connected node exists before attempting sync.
 * Retries up to 3 times with exponential backoff.
 */
suspend fun checkConnection(context: android.content.Context, maxRetries: Int = 3): Boolean {
    var attempt = 0
    while (attempt < maxRetries) {
        try {
            Log.d("DataLayerSync", "Checking connection (attempt ${attempt + 1}/$maxRetries)")
            // Use NodeClient to get connected nodes
            val nodeClient = Wearable.getNodeClient(context)
            val nodes = Tasks.await(nodeClient.connectedNodes, 10, java.util.concurrent.TimeUnit.SECONDS)
            val hasConnection = nodes.isNotEmpty()
            
            if (hasConnection) {
                Log.d("DataLayerSync", "Connection verified: ${nodes.size} node(s) connected")
                return true
            } else {
                Log.w("DataLayerSync", "No connected nodes found (attempt ${attempt + 1}/$maxRetries)")
            }
        } catch (e: Exception) {
            Log.w("DataLayerSync", "Connection check failed (attempt ${attempt + 1}/$maxRetries): ${e.message}")
        }
        
        attempt++
        if (attempt < maxRetries) {
            // Exponential backoff: 500ms, 1000ms, 2000ms
            val delayMs = 500L * (1 shl (attempt - 1))
            delay(delayMs)
        }
    }
    
    Log.e("DataLayerSync", "Connection check failed after $maxRetries attempts")
    return false
}

suspend fun sendSyncRequest(dataClient: DataClient, transactionId: String, context: android.content.Context? = null): Boolean {
    val maxRetries = 3
    var attempt = 0
    
    while (attempt < maxRetries) {
        try {
            Log.d("DataLayerSync", "Starting handshake for transaction: $transactionId (attempt ${attempt + 1}/$maxRetries)")
            
            // Check connection before attempting sync if context is provided
            if (context != null) {
                val hasConnection = checkConnection(context)
                if (!hasConnection) {
                    Log.e("DataLayerSync", "No connection available for transaction: $transactionId (attempt ${attempt + 1}/$maxRetries)")
                    if (attempt < maxRetries - 1) {
                        // Exponential backoff with jitter
                        val baseDelay = 500L * (1 shl attempt)
                        val jitter = (0..100).random().toLong()
                        delay(baseDelay + jitter)
                        attempt++
                        continue
                    }
                    return false
                }
            }
            
            // Register waiter BEFORE sending request to avoid race condition
            val ackWaiter = SyncHandshakeManager.registerAckWaiter(transactionId)
            
            val requestPath = DataLayerPaths.buildPath(DataLayerPaths.SYNC_REQUEST_PREFIX, transactionId)
            val request = PutDataMapRequest.create(requestPath).apply {
                dataMap.putString("transactionId", transactionId)
                dataMap.putString("timestamp", System.currentTimeMillis().toString())
            }.asPutDataRequest().setUrgent()
            
            Log.d("DataLayerSync", "Sending sync request for transaction: $transactionId")
            dataClient.putDataItem(request)
            
            // Small delay to allow message delivery
            delay(100)
            
            Log.d("DataLayerSync", "Waiting for acknowledgment for transaction: $transactionId")
            // Wait for acknowledgment with timeout (using default for now, context-based timeout can be added later)
            val ackReceived = withTimeoutOrNull(DataLayerListenerService.HANDSHAKE_TIMEOUT_MS) {
                ackWaiter.await()
                Log.d("DataLayerSync", "Received acknowledgment for transaction: $transactionId")
                true
            } ?: false
            
            if (!ackReceived) {
                Log.e("DataLayerSync", "Handshake timeout for transaction: $transactionId after ${DataLayerListenerService.HANDSHAKE_TIMEOUT_MS}ms (attempt ${attempt + 1}/$maxRetries)")
                if (attempt < maxRetries - 1) {
                    // Exponential backoff with jitter
                    val baseDelay = 500L * (1 shl attempt)
                    val jitter = (0..100).random().toLong()
                    delay(baseDelay + jitter)
                    attempt++
                    continue
                }
                SyncHandshakeManager.cleanup(transactionId)
                return false
            } else {
                Log.d("DataLayerSync", "Handshake successful for transaction: $transactionId")
                return true
            }
        } catch (exception: Exception) {
            Log.e("DataLayerSync", "Error sending sync request for transaction: $transactionId (attempt ${attempt + 1}/$maxRetries): ${exception.message}", exception)
            if (attempt < maxRetries - 1) {
                // Exponential backoff with jitter
                val baseDelay = 500L * (1 shl attempt)
                val jitter = (0..100).random().toLong()
                delay(baseDelay + jitter)
                attempt++
                continue
            }
            SyncHandshakeManager.cleanup(transactionId)
            return false
        }
    }
    
    SyncHandshakeManager.cleanup(transactionId)
    return false
}

suspend fun waitForSyncCompletion(transactionId: String): Boolean {
    return try {
        val completionWaiter = SyncHandshakeManager.registerCompletionWaiter(transactionId)
        
        // await() handles already-completed deferreds correctly, so we can use it directly
        // But check first for early return and logging
        if (completionWaiter.isCompleted) {
            Log.d("DataLayerSync", "Completion waiter already completed for transaction: $transactionId")
            SyncHandshakeManager.cleanup(transactionId)
            return true
        }
        
        val completionReceived = withTimeoutOrNull(DataLayerListenerService.COMPLETION_TIMEOUT_MS) {
            completionWaiter.await()
            true
        } ?: false
        
        if (!completionReceived) {
            Log.w("DataLayerSync", "Completion timeout for transaction: $transactionId (data may have been received)")
        }
        
        SyncHandshakeManager.cleanup(transactionId)
        completionReceived
    } catch (exception: Exception) {
        Log.e("DataLayerSync", "Error waiting for sync completion", exception)
        SyncHandshakeManager.cleanup(transactionId)
        false
    }
}

suspend fun sendWorkoutStore(dataClient: DataClient, workoutStore: WorkoutStore) {
    val transactionId = UUID.randomUUID().toString()
    Log.d("DataLayerSync", "Starting workout store sync, transactionId=$transactionId")
    try {
        // Send sync request and wait for acknowledgment
        val handshakeSuccess = sendSyncRequest(dataClient, transactionId)
        if (!handshakeSuccess) {
            Log.e("DataLayerSync", "Failed to establish connection for workout store sync (transaction: $transactionId)")
            throw SyncError.HandshakeError(transactionId, 0)
        }

        // Register completion and error waiters BEFORE sending data
        val completionWaiter = SyncHandshakeManager.registerCompletionWaiter(transactionId)
        val errorWaiter = SyncHandshakeManager.registerErrorWaiter(transactionId)

        // Send workout store data
        val jsonString = fromWorkoutStoreToJSON(workoutStore)
        val compressedData = compressString(jsonString)
        val workoutStorePath = DataLayerPaths.buildPath(DataLayerPaths.WORKOUT_STORE_PREFIX, transactionId)
        val request = PutDataMapRequest.create(workoutStorePath).apply {
            dataMap.putByteArray("compressedJson", compressedData)
            dataMap.putString("timestamp", System.currentTimeMillis().toString())
            dataMap.putString("transactionId", transactionId)
        }.asPutDataRequest().setUrgent()

        dataClient.putDataItem(request)
        
        // Small delay to allow message delivery
        delay(100)

        // Use default timeout for workout store (single payload, no chunks)
        val completionTimeout = DataLayerListenerService.calculateCompletionTimeout(1)
        Log.d("DataLayerSync", "Using completion timeout: ${completionTimeout}ms for workout store, transaction: $transactionId")

        // Wait for either completion, error, or timeout
        val result = withTimeoutOrNull(completionTimeout) {
            select<Pair<Boolean, String?>> {
                completionWaiter.onAwait.invoke {
                    Pair(true, null)
                }
                errorWaiter.onAwait.invoke { errorMessage ->
                    Pair(false, errorMessage)
                }
            }
        }
        
        when {
            result == null -> {
                // Timeout occurred
                Log.e("DataLayerSync", "Completion timeout for workout store transaction: $transactionId (timeout: ${completionTimeout}ms)")
                SyncHandshakeManager.cleanup(transactionId)
                throw SyncError.TimeoutError(transactionId, completionTimeout, 0)
            }
            result.first -> {
                // Completion received
                Log.d("DataLayerSync", "Sync completed successfully for transaction: $transactionId")
                SyncHandshakeManager.cleanup(transactionId)
            }
            else -> {
                // Error received
                val errorMessage = result.second ?: "Unknown error"
                Log.e("DataLayerSync", "Sync error for workout store transaction: $transactionId, error: $errorMessage")
                SyncHandshakeManager.cleanup(transactionId)
                // Parse error type from message
                val syncError = when {
                    errorMessage.startsWith("MISSING_CHUNKS:") -> {
                        val missingIndices = parseMissingChunks(errorMessage)
                        SyncError.ChunkError(transactionId, missingIndices, 0, 0, 0)
                    }
                    else -> SyncError.ProcessingError(transactionId, "workout store sync", Exception(errorMessage), 0)
                }
                throw syncError
            }
        }
    } catch (cancellationException: CancellationException) {
        SyncHandshakeManager.cleanup(transactionId)
        cancellationException.printStackTrace()
        throw cancellationException
    } catch (exception: Exception) {
        SyncHandshakeManager.cleanup(transactionId)
        Log.e("DataLayerSync", "Error sending workout store", exception)
        throw exception
    }
}

suspend fun sendAppBackup(dataClient: DataClient, appBackup: AppBackup, context: android.content.Context? = null) {
    val transactionId = UUID.randomUUID().toString()
    Log.d("DataLayerSync", "Starting app backup, transactionId=$transactionId")
    try {
        // Check if watch is connected before attempting sync
        // This prevents sync attempts when watch is not available (e.g., during app uninstall)
        if (context != null) {
            val hasConnection = checkConnection(context)
            if (!hasConnection) {
                Log.d("DataLayerSync", "Skipping app backup sync - watch not connected (transaction: $transactionId)")
                return
            }
        }
        
        // Send sync request and wait for acknowledgment
        val handshakeSuccess = sendSyncRequest(dataClient, transactionId, context)
        if (!handshakeSuccess) {
            Log.e("DataLayerSync", "Failed to establish connection for app backup sync (transaction: $transactionId)")
            throw SyncError.HandshakeError(transactionId, 0)
        }

        // Register completion and error waiters BEFORE sending data
        val completionWaiter = SyncHandshakeManager.registerCompletionWaiter(transactionId)
        val errorWaiter = SyncHandshakeManager.registerErrorWaiter(transactionId)

        val jsonString = fromAppBackupToJSON(appBackup)
        val chunkSize = 50000 // Adjust the chunk size as needed
        val compressedData = compressString(jsonString)
        val chunks = compressedData.asList().chunked(chunkSize).map { it.toByteArray() }

        val startPath = DataLayerPaths.buildPath(DataLayerPaths.APP_BACKUP_START_PREFIX, transactionId)
        val startRequest = PutDataMapRequest.create(startPath).apply {
            dataMap.putBoolean("isStart", true)
            dataMap.putInt("chunksCount", chunks.size)
            dataMap.putString("timestamp", System.currentTimeMillis().toString())
            dataMap.putString("transactionId", transactionId)
        }.asPutDataRequest().setUrgent()

        dataClient.putDataItem(startRequest)

        delay(500)

        // Send chunks with indices
        chunks.forEachIndexed { index, chunk ->
            val isLastChunk = index == chunks.size - 1
            val chunkPath = DataLayerPaths.buildPath(DataLayerPaths.APP_BACKUP_CHUNK_PREFIX, transactionId, index)

            val request = PutDataMapRequest.create(chunkPath).apply {
                dataMap.putByteArray("chunk", chunk)
                dataMap.putInt("chunkIndex", index)
                if(isLastChunk) {
                    dataMap.putBoolean("isLastChunk", true)
                }
                dataMap.putString("timestamp", System.currentTimeMillis().toString())
                dataMap.putString("transactionId", transactionId)
            }.asPutDataRequest().setUrgent()

            dataClient.putDataItem(request)

            if (!isLastChunk) {
                delay(500)
            }
        }
        
        // Small delay after last chunk to allow message delivery
        delay(100)

        // Calculate dynamic timeout based on chunk count
        val completionTimeout = DataLayerListenerService.calculateCompletionTimeout(chunks.size)
        Log.d("DataLayerSync", "Using dynamic completion timeout: ${completionTimeout}ms for ${chunks.size} chunks, transaction: $transactionId")

        // Wait for either completion, error, or timeout - with retry logic
        var retryAttempt = 0
        val maxRetries = 5 // Increased from 3 to 5 for better recovery
        var currentCompletionWaiter = completionWaiter
        var currentErrorWaiter = errorWaiter

        while (retryAttempt <= maxRetries) {
            // Use select which handles already-completed deferreds correctly
            // onAwait will immediately return if the deferred is already completed
            val result = withTimeoutOrNull(completionTimeout) {
                select<Pair<Boolean, String?>> {
                    currentCompletionWaiter.onAwait.invoke {
                        Pair(true, null)
                    }
                    currentErrorWaiter.onAwait.invoke { errorMessage ->
                        Pair(false, errorMessage)
                    }
                }
            }
            
            // Check if completion was already received (select handles this, but we check for logging)
            if (currentCompletionWaiter.isCompleted && result?.first != true) {
                Log.d("DataLayerSync", "Completion waiter was already completed for backup transaction: $transactionId")
                SyncHandshakeManager.cleanup(transactionId)
                return
            }
            
            when {
                result == null -> {
                    // Timeout occurred
                    Log.e("DataLayerSync", "Completion timeout for backup transaction: $transactionId (attempt $retryAttempt)")
                    if (retryAttempt < maxRetries) {
                        // Exponential backoff with jitter for timeout retries
                        val baseDelay = 500L * (1 shl retryAttempt)
                        val jitter = (0..200).random().toLong()
                        delay(baseDelay + jitter)
                        retryAttempt++
                        // Re-register waiters for retry
                        currentCompletionWaiter = SyncHandshakeManager.registerCompletionWaiter(transactionId)
                        currentErrorWaiter = SyncHandshakeManager.registerErrorWaiter(transactionId)
                        continue
                    }
                    SyncHandshakeManager.cleanup(transactionId)
                    throw Exception("Sync timed out after $maxRetries retry attempts (transaction: $transactionId) - data may not have been received")
                }
                result.first -> {
                    // Completion received
                    Log.d("DataLayerSync", "Sync completed successfully for backup transaction: $transactionId")
                    SyncHandshakeManager.cleanup(transactionId)
                    return
                }
                else -> {
                    // Error received
                    val errorMessage = result.second ?: "Unknown error"
                    Log.e("DataLayerSync", "Sync error for backup transaction: $transactionId, error: $errorMessage (attempt $retryAttempt)")
                    
                    // Check if it's a missing chunks error and we can retry
                    if (errorMessage.startsWith("MISSING_CHUNKS:") && retryAttempt < maxRetries) {
                        val missingIndices = parseMissingChunks(errorMessage)
                        if (missingIndices.isNotEmpty()) {
                            // Check if completion was already received before starting retry
                            if (SyncHandshakeManager.hasCompletion(transactionId)) {
                                Log.d("DataLayerSync", "Completion already received before retry for transaction: $transactionId")
                                SyncHandshakeManager.cleanup(transactionId)
                                return
                            }
                            
                            Log.d("DataLayerSync", "Attempting retry ${retryAttempt + 1} for missing chunks: $missingIndices")
                            try {
                                // Register new waiters for the retry attempt
                                // registerCompletionWaiter now handles race conditions atomically
                                currentCompletionWaiter = SyncHandshakeManager.registerCompletionWaiter(transactionId)
                                currentErrorWaiter = SyncHandshakeManager.registerErrorWaiter(transactionId)
                                
                                // Check immediately after registration if completion was already received
                                // This handles the case where completion arrives between error and retry registration
                                if (currentCompletionWaiter.isCompleted) {
                                    Log.d("DataLayerSync", "Completion already received when registering retry waiter for transaction: $transactionId")
                                    SyncHandshakeManager.cleanup(transactionId)
                                    return
                                }
                                
                                retryMissingChunks(dataClient, transactionId, missingIndices, chunks)
                                retryAttempt++
                                // Exponential backoff with jitter: 500ms, 1000ms, 2000ms, 4000ms, 8000ms
                                val baseDelay = 500L * (1 shl (retryAttempt - 1))
                                val jitter = (0..200).random().toLong()
                                delay(baseDelay + jitter)
                                Log.d("DataLayerSync", "Retry delay: ${baseDelay + jitter}ms for attempt $retryAttempt")
                                
                                // Check again before continuing loop (completion might have arrived during retry)
                                if (currentCompletionWaiter.isCompleted) {
                                    Log.d("DataLayerSync", "Completion received during retry for transaction: $transactionId")
                                    SyncHandshakeManager.cleanup(transactionId)
                                    return
                                }
                                
                                continue
                            } catch (retryException: Exception) {
                                Log.e("DataLayerSync", "Retry failed: ${retryException.message}", retryException)
                                SyncHandshakeManager.cleanup(transactionId)
                                throw Exception("Sync failed after retry attempt: ${retryException.message}")
                            }
                        }
                    }
                    
                    // Not a retryable error or max retries reached
                    SyncHandshakeManager.cleanup(transactionId)
                    val syncError = when {
                        errorMessage.startsWith("MISSING_CHUNKS:") -> {
                            val missingIndices = parseMissingChunks(errorMessage)
                            // Parse expected and received from error message
                            val expectedMatch = Regex("Expected (\\d+) chunks").find(errorMessage)
                            val receivedMatch = Regex("received (\\d+)").find(errorMessage)
                            val expected = expectedMatch?.groupValues?.get(1)?.toIntOrNull() ?: chunks.size
                            val received = receivedMatch?.groupValues?.get(1)?.toIntOrNull() ?: (chunks.size - missingIndices.size)
                            SyncError.ChunkError(transactionId, missingIndices, expected, received, retryAttempt)
                        }
                        else -> SyncError.ProcessingError(transactionId, "app backup sync", Exception(errorMessage), retryAttempt)
                    }
                    throw syncError
                }
            }
        }
    } catch (cancellationException: CancellationException) {
        SyncHandshakeManager.cleanup(transactionId)
        cancellationException.printStackTrace()
        throw cancellationException
    } catch (exception: Exception) {
        SyncHandshakeManager.cleanup(transactionId)
        Log.e("DataLayerSync", "Error sending app backup", exception)
        throw exception
    } finally {
        cleanupAppBackupTransactionDataItems(dataClient, transactionId)
    }
}

private suspend fun cleanupAppBackupTransactionDataItems(
    dataClient: DataClient,
    transactionId: String
) {
    val transactionPaths = listOf(
        DataLayerPaths.buildPath(DataLayerPaths.SYNC_REQUEST_PREFIX, transactionId),
        DataLayerPaths.buildPath(DataLayerPaths.APP_BACKUP_START_PREFIX, transactionId),
        DataLayerPaths.buildPath(DataLayerPaths.APP_BACKUP_CHUNK_PREFIX, transactionId)
    )

    transactionPaths.forEach { path ->
        try {
            val uri = Uri.Builder()
                .scheme("wear")
                .path(path)
                .build()
            val deletedCount = Tasks.await(
                dataClient.deleteDataItems(uri, DataClient.FILTER_PREFIX)
            )
            Log.d(
                "DataLayerSync",
                "Cleaned up $deletedCount DataItem(s) for path=$path transaction=$transactionId"
            )
        } catch (exception: Exception) {
            Log.w(
                "DataLayerSync",
                "Failed to clean up DataItems for path=$path transaction=$transactionId: ${exception.message}"
            )
        }
    }
}

/**
 * Parses missing chunk indices from error message
 * Expected format: "MISSING_CHUNKS: Expected 10 chunks, received 7. Missing indices: [2, 5, 7]"
 */
private fun parseMissingChunks(errorMessage: String): List<Int> {
    return try {
        val indicesPattern = Regex("Missing indices: \\[(\\d+(?:, \\d+)*)\\]")
        val match = indicesPattern.find(errorMessage)
        match?.groupValues?.get(1)?.split(", ")?.mapNotNull { it.toIntOrNull() } ?: emptyList()
    } catch (e: Exception) {
        Log.e("DataLayerSync", "Failed to parse missing chunks from error message: $errorMessage", e)
        emptyList()
    }
}

/**
 * Retries sending specific missing chunks
 */
private suspend fun retryMissingChunks(
    dataClient: DataClient,
    transactionId: String,
    missingIndices: List<Int>,
    chunks: List<ByteArray>
) {
    if (missingIndices.isEmpty()) {
        Log.w("DataLayerSync", "retryMissingChunks called with empty missing indices list")
        return
    }

    Log.d("DataLayerSync", "Retrying ${missingIndices.size} missing chunks for transaction: $transactionId, indices: $missingIndices")

    // Register new waiters for retry attempt
    val completionWaiter = SyncHandshakeManager.registerCompletionWaiter(transactionId)
    val errorWaiter = SyncHandshakeManager.registerErrorWaiter(transactionId)

    // Send missing chunks one by one
    missingIndices.forEachIndexed { retryIndex, chunkIndex ->
        if (chunkIndex < 0 || chunkIndex >= chunks.size) {
            Log.e("DataLayerSync", "Invalid chunk index in retry: $chunkIndex (total chunks: ${chunks.size})")
            return@forEachIndexed
        }

        val chunk = chunks[chunkIndex]
        val isLastRetryChunk = retryIndex == missingIndices.size - 1

        val chunkPath = DataLayerPaths.buildPath(
            DataLayerPaths.APP_BACKUP_CHUNK_PREFIX,
            transactionId,
            chunkIndex
        )
        val request = PutDataMapRequest.create(chunkPath).apply {
            dataMap.putByteArray("chunk", chunk)
            dataMap.putInt("chunkIndex", chunkIndex)
            dataMap.putBoolean("isRetry", true)
            if (isLastRetryChunk) {
                dataMap.putBoolean("isLastRetryChunk", true)
            }
            dataMap.putString("timestamp", System.currentTimeMillis().toString())
            dataMap.putString("transactionId", transactionId)
        }.asPutDataRequest().setUrgent()

        dataClient.putDataItem(request)

        if (!isLastRetryChunk) {
            delay(500)
        }
    }

    // Small delay after last retry chunk
    delay(100)
    Log.d("DataLayerSync", "Finished sending retry chunks for transaction: $transactionId")
}

