package com.gabstra.myworkoutassistant

import android.annotation.SuppressLint
import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
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
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.HeartRateRecord
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

private val backupFileWriteMutex = Mutex()

// Helper object to manage sync handshake state
object SyncHandshakeManager {
    private val pendingAcks = ConcurrentHashMap<String, CompletableDeferred<Unit>>()
    private val pendingCompletions = ConcurrentHashMap<String, CompletableDeferred<Unit>>()
    private val pendingErrors = ConcurrentHashMap<String, CompletableDeferred<String>>()

    fun registerAckWaiter(transactionId: String): CompletableDeferred<Unit> {
        val deferred = CompletableDeferred<Unit>()
        pendingAcks[transactionId] = deferred
        return deferred
    }

    fun registerCompletionWaiter(transactionId: String): CompletableDeferred<Unit> {
        // Use compute to atomically check if there's already a completed deferred
        // This prevents race conditions where completion arrives between registration and wait
        return pendingCompletions.compute(transactionId) { _, existing ->
            if (existing != null && existing.isCompleted) {
                // Reuse the already-completed deferred
                existing
            } else {
                // Create new deferred, but cancel the old one if it exists and isn't completed
                existing?.cancel()
                CompletableDeferred<Unit>()
            }
        } ?: CompletableDeferred<Unit>()
    }

    fun registerErrorWaiter(transactionId: String): CompletableDeferred<String> {
        // Use compute to atomically check if there's already a completed deferred
        // This prevents race conditions where error arrives between registration and wait
        return pendingErrors.compute(transactionId) { _, existing ->
            if (existing != null && existing.isCompleted) {
                // Reuse the already-completed deferred
                existing
            } else {
                // Create new deferred, but cancel the old one if it exists and isn't completed
                existing?.cancel()
                CompletableDeferred<String>()
            }
        } ?: CompletableDeferred<String>()
    }
    
    fun hasError(transactionId: String): Boolean {
        val deferred = pendingErrors[transactionId]
        return deferred?.isCompleted == true
    }

    fun completeAck(transactionId: String) {
        pendingAcks.remove(transactionId)?.complete(Unit)
    }

    fun completeCompletion(transactionId: String) {
        // Use compute to atomically complete and handle race conditions
        // This ensures we complete the deferred even if it's being checked/waiting concurrently
        pendingCompletions.compute(transactionId) { _, deferred ->
            deferred?.let {
                if (!it.isCompleted) {
                    it.complete(Unit)
                }
            }
            // Return null to remove from map after completion
            null
        }
    }

    fun hasCompletion(transactionId: String): Boolean {
        val deferred = pendingCompletions[transactionId]
        return deferred?.isCompleted == true
    }

    fun completeError(transactionId: String, errorMessage: String) {
        // Use compute to atomically complete and handle race conditions
        // This ensures we complete the deferred even if it's being checked/waiting concurrently
        pendingErrors.compute(transactionId) { _, deferred ->
            deferred?.let {
                if (!it.isCompleted) {
                    it.complete(errorMessage)
                }
            }
            // Return null to remove from map after completion
            null
        }
    }

    fun cleanup(transactionId: String) {
        pendingAcks.remove(transactionId)?.cancel()
        pendingCompletions.remove(transactionId)?.cancel()
        pendingErrors.remove(transactionId)?.cancel()
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

fun formatSecondsToMinutesSeconds(seconds: Int): String {
    val minutes = (seconds % 3600) / 60
    val remainingSeconds = seconds % 60
    return String.format("%02d:%02d", minutes, remainingSeconds)
}

fun formatMillisecondsToMinutesSeconds(milliseconds: Int): String {
    val seconds = milliseconds / 1000

    val minutes = (seconds % 3600) / 60
    val remainingSeconds = seconds % 60
    val remainingMilliseconds = milliseconds % 1000
    return String.format("%02d:%02d:%03d", minutes, remainingSeconds, remainingMilliseconds)
}

fun findWorkoutComponentByIdInWorkouts(workouts: List<Workout>, id: UUID): WorkoutComponent? {
    for(workout in workouts){
        for (workoutComponent in workout.workoutComponents) {
            if (workoutComponent.id == id) {
                return workoutComponent
            }

            if(workoutComponent is Superset){
                workoutComponent.exercises.forEach { exercise ->
                    if(exercise.id == id){
                        return exercise
                    }
                }
            }
        }
    }


    return null
}

fun findWorkoutComponentByIdInWorkout(workout: Workout, id: UUID): WorkoutComponent? {
    for (workoutComponent in workout.workoutComponents) {
        if (workoutComponent.id == id) {
            return workoutComponent
        }

        if(workoutComponent is Superset){
            if (workoutComponent.id == id) {
                return workoutComponent
            }

            workoutComponent.exercises.forEach { exercise ->
                if(exercise.id == id){
                    return exercise
                }
            }
        }
    }

    return null
}

fun writeJsonToDownloadsFolder(context: Context, fileName: String, fileContent: String) {
    val contentValues = ContentValues().apply {
        put(MediaStore.MediaColumns.DISPLAY_NAME, fileName)
        put(MediaStore.MediaColumns.MIME_TYPE, "application/json")
        put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
    }

    val resolver = context.contentResolver
    val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, contentValues)

    uri?.let {
        resolver.openOutputStream(it).use { outputStream ->
            outputStream?.write(fileContent.toByteArray())
        }
    } ?: run {
        android.os.Handler(android.os.Looper.getMainLooper()).post {
            Toast.makeText(context, "Failed to write to downloads folder", Toast.LENGTH_SHORT).show()
        }
    }
}

/**
 * Reads a JSON file from Downloads folder using MediaStore.
 * Returns the file content as a string, or null if not found.
 */
suspend fun readJsonFromDownloadsFolder(context: Context, fileName: String): String? {
    return withContext(Dispatchers.IO) {
        try {
            val resolver = context.contentResolver
            val projection = arrayOf(
                MediaStore.Downloads._ID,
                MediaStore.Downloads.DISPLAY_NAME
            )
            val selection = "${MediaStore.Downloads.DISPLAY_NAME} = ?"
            val selectionArgs = arrayOf(fileName)
            
            resolver.query(
                MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                projection,
                selection,
                selectionArgs,
                null
            )?.use { cursor ->
                if (cursor.moveToFirst()) {
                    val idIndex = cursor.getColumnIndexOrThrow(MediaStore.Downloads._ID)
                    val id = cursor.getLong(idIndex)
                    val uri = ContentUris.withAppendedId(
                        MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                        id
                    )
                    
                    resolver.openInputStream(uri)?.use { inputStream ->
                        inputStream.bufferedReader().use { reader ->
                            reader.readText()
                        }
                    }
                } else {
                    null
                }
            }
        } catch (e: Exception) {
            Log.e("Utils", "Error reading file from Downloads folder: $fileName", e)
            null
        }
    }
}

/**
 * Helper function to find a file URI in Downloads folder.
 * Returns the URI if found, null otherwise.
 */
private suspend fun findFileInDownloadsFolder(context: Context, fileName: String): android.net.Uri? {
    return withContext(Dispatchers.IO) {
        try {
            val resolver = context.contentResolver
            val projection = arrayOf(MediaStore.Downloads._ID)
            val selection = "${MediaStore.Downloads.DISPLAY_NAME} = ?"
            val selectionArgs = arrayOf(fileName)
            
            resolver.query(
                MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                projection,
                selection,
                selectionArgs,
                null
            )?.use { cursor ->
                if (cursor.moveToFirst()) {
                    val idIndex = cursor.getColumnIndexOrThrow(MediaStore.Downloads._ID)
                    val id = cursor.getLong(idIndex)
                    ContentUris.withAppendedId(
                        MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                        id
                    )
                } else {
                    null
                }
            }
        } catch (e: Exception) {
            Log.e("Utils", "Error finding file in Downloads folder: $fileName", e)
            null
        }
    }
}

/**
 * Finds all files with the given name in Downloads folder and returns their URIs.
 * Used to clean up duplicate backup files.
 */
private suspend fun findAllFilesInDownloadsFolder(context: Context, fileName: String): List<android.net.Uri> {
    return withContext(Dispatchers.IO) {
        try {
            val resolver = context.contentResolver
            val projection = arrayOf(MediaStore.Downloads._ID, MediaStore.Downloads.DISPLAY_NAME)
            val selection = "${MediaStore.Downloads.DISPLAY_NAME} = ?"
            val selectionArgs = arrayOf(fileName)
            
            val uris = mutableListOf<android.net.Uri>()
            resolver.query(
                MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                projection,
                selection,
                selectionArgs,
                null
            )?.use { cursor ->
                val idIndex = cursor.getColumnIndexOrThrow(MediaStore.Downloads._ID)
                val nameIndex = cursor.getColumnIndexOrThrow(MediaStore.Downloads.DISPLAY_NAME)
                while (cursor.moveToNext()) {
                    val id = cursor.getLong(idIndex)
                    val name = cursor.getString(nameIndex)
                    // Double-check the name matches (MediaStore might have variations)
                    if (name == fileName) {
                        uris.add(
                            ContentUris.withAppendedId(
                                MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                                id
                            )
                        )
                    }
                }
            }
            uris
        } catch (e: Exception) {
            Log.e("Utils", "Error finding all files in Downloads folder: $fileName", e)
            emptyList()
        }
    }
}

private data class BackupFileEntry(
    val uri: android.net.Uri,
    val name: String,
    val dateModified: Long
)

private fun matchesBackupFileName(name: String, exactFileName: String): Boolean {
    val baseName = exactFileName.removeSuffix(".json")
    val escapedBaseName = Regex.escape(baseName)
    val pattern = Regex(
        "^$escapedBaseName(?:\\.json(?:\\s*\\(\\d+\\))?|\\s*\\(\\d+\\)\\.json)$",
        RegexOption.IGNORE_CASE
    )
    return pattern.matches(name)
}

private fun deleteBackupFile(context: Context, uri: android.net.Uri): Boolean {
    return context.contentResolver.delete(uri, null, null) > 0
}

/**
 * Finds all backup files that match the automatic backup pattern.
 * This includes exact matches and files that might have been created with variations.
 * Returns a list of URIs with their display names for content comparison.
 */
private suspend fun findAllBackupFilesInDownloadsFolder(context: Context, exactFileName: String): List<BackupFileEntry> {
    return withContext(Dispatchers.IO) {
        try {
            val resolver = context.contentResolver
            val projection = arrayOf(
                MediaStore.MediaColumns._ID,
                MediaStore.MediaColumns.DISPLAY_NAME,
                MediaStore.MediaColumns.DATE_MODIFIED,
                MediaStore.MediaColumns.RELATIVE_PATH
            )

            fun queryCollection(
                collectionUri: android.net.Uri,
                limitToDownloads: Boolean,
                restrictToOwner: Boolean
            ): List<BackupFileEntry> {
                val files = mutableListOf<BackupFileEntry>()
                val baseSelectionParts = mutableListOf<String>()
                val baseSelectionArgs = mutableListOf<String>()

                if (restrictToOwner && android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.Q) {
                    baseSelectionParts.add("${MediaStore.MediaColumns.OWNER_PACKAGE_NAME} = ?")
                    baseSelectionArgs.add(context.packageName)
                }

                if (limitToDownloads) {
                    baseSelectionParts.add("${MediaStore.MediaColumns.RELATIVE_PATH} LIKE ?")
                    baseSelectionArgs.add("${Environment.DIRECTORY_DOWNLOADS}/%")
                }

                val exactSelectionParts = baseSelectionParts.toMutableList().apply {
                    add("${MediaStore.MediaColumns.DISPLAY_NAME} = ?")
                }
                val exactSelection = exactSelectionParts.joinToString(" AND ")
                val exactSelectionArgs = (baseSelectionArgs + exactFileName).toTypedArray()

                resolver.query(
                    collectionUri,
                    projection,
                    exactSelection,
                    exactSelectionArgs,
                    null
                )?.use { cursor ->
                    val idIndex = cursor.getColumnIndexOrThrow(MediaStore.MediaColumns._ID)
                    val nameIndex = cursor.getColumnIndexOrThrow(MediaStore.MediaColumns.DISPLAY_NAME)
                    val dateIndex = cursor.getColumnIndexOrThrow(MediaStore.MediaColumns.DATE_MODIFIED)
                    while (cursor.moveToNext()) {
                        val id = cursor.getLong(idIndex)
                        val name = cursor.getString(nameIndex)
                        val dateModified = cursor.getLong(dateIndex)
                        if (name == exactFileName) {
                            files.add(
                                BackupFileEntry(
                                    ContentUris.withAppendedId(collectionUri, id),
                                    name,
                                    dateModified
                                )
                            )
                        }
                    }
                }

                val allSelection = if (baseSelectionParts.isEmpty()) {
                    null
                } else {
                    baseSelectionParts.joinToString(" AND ")
                }
                val allSelectionArgs = if (baseSelectionArgs.isEmpty()) {
                    null
                } else {
                    baseSelectionArgs.toTypedArray()
                }

                val allFiles = mutableListOf<BackupFileEntry>()
                resolver.query(
                    collectionUri,
                    projection,
                    allSelection,
                    allSelectionArgs,
                    "${MediaStore.MediaColumns.DATE_MODIFIED} DESC"
                )?.use { cursor ->
                    val idIndex = cursor.getColumnIndexOrThrow(MediaStore.MediaColumns._ID)
                    val nameIndex = cursor.getColumnIndexOrThrow(MediaStore.MediaColumns.DISPLAY_NAME)
                    val dateIndex = cursor.getColumnIndexOrThrow(MediaStore.MediaColumns.DATE_MODIFIED)
                    while (cursor.moveToNext()) {
                        val id = cursor.getLong(idIndex)
                        val name = cursor.getString(nameIndex)
                        val dateModified = cursor.getLong(dateIndex)
                        if (matchesBackupFileName(name, exactFileName)) {
                            allFiles.add(
                                BackupFileEntry(
                                    ContentUris.withAppendedId(collectionUri, id),
                                    name,
                                    dateModified
                                )
                            )
                        }
                    }
                }

                val existingUris = files.map { it.uri }.toSet()
                for (file in allFiles) {
                    if (file.uri !in existingUris) {
                        files.add(file)
                    }
                }

                return files
            }

            val downloadsFiles = queryCollection(
                MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                limitToDownloads = false,
                restrictToOwner = true
            )

            val downloadsFallbackFiles = if (downloadsFiles.isEmpty()) {
                Log.d(
                    "Utils",
                    "No backup files found in MediaStore.Downloads for owner; retrying without owner filter"
                )
                queryCollection(
                    MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                    limitToDownloads = false,
                    restrictToOwner = false
                )
            } else {
                emptyList()
            }

            val resolvedDownloadsFiles = if (downloadsFiles.isEmpty()) {
                downloadsFallbackFiles
            } else {
                downloadsFiles
            }

            val filesCollectionFiles = if (resolvedDownloadsFiles.isEmpty()) {
                Log.d(
                    "Utils",
                    "No backup files found in MediaStore.Downloads; checking MediaStore.Files for ${Environment.DIRECTORY_DOWNLOADS}"
                )
                queryCollection(
                    MediaStore.Files.getContentUri(MediaStore.VOLUME_EXTERNAL),
                    limitToDownloads = true,
                    restrictToOwner = false
                )
            } else {
                emptyList()
            }

            val files = (resolvedDownloadsFiles + filesCollectionFiles).distinctBy { it.uri }

            files.sortedWith(
                compareBy<BackupFileEntry> { it.name != exactFileName }
                    .thenByDescending { it.dateModified }
            )
        } catch (e: Exception) {
            Log.e("Utils", "Error finding all backup files in Downloads folder: $exactFileName", e)
            emptyList()
        }
    }
}

/**
 * Reads the content of a file from Downloads folder.
 * Returns null if the file doesn't exist or can't be read.
 */
private suspend fun readFileContentFromDownloadsFolder(context: Context, uri: android.net.Uri): String? {
    return withContext(Dispatchers.IO) {
        try {
            context.contentResolver.openInputStream(uri)?.use { inputStream ->
                inputStream.bufferedReader().readText()
            }
        } catch (e: Exception) {
            Log.e("Utils", "Error reading file content from Downloads folder", e)
            null
        }
    }
}

/**
 * Finds all backup files matching both automatic and manual backup patterns.
 * - Automatic backups: workout_store_backup.json (and variations)
 * - Manual backups: workout_backup_*.json
 */
private suspend fun findAllBackupFiles(context: Context): List<BackupFileEntry> {
    return withContext(Dispatchers.IO) {
        try {
            val automaticBackups = findAllBackupFilesInDownloadsFolder(context, "workout_store_backup.json")
            
            // Find manual backups (workout_backup_*.json pattern)
            val manualBackups = findManualBackupFiles(context)
            
            // Combine and deduplicate by URI
            val allBackups = (automaticBackups + manualBackups).distinctBy { it.uri }
            
            Log.d("Utils", "Found ${allBackups.size} total backup files (${automaticBackups.size} automatic, ${manualBackups.size} manual)")
            allBackups
        } catch (e: Exception) {
            Log.e("Utils", "Error finding all backup files", e)
            emptyList()
        }
    }
}

/**
 * Finds manual backup files matching the pattern workout_backup_*.json
 */
private suspend fun findManualBackupFiles(context: Context): List<BackupFileEntry> {
    return withContext(Dispatchers.IO) {
        try {
            val resolver = context.contentResolver
            val projection = arrayOf(
                MediaStore.MediaColumns._ID,
                MediaStore.MediaColumns.DISPLAY_NAME,
                MediaStore.MediaColumns.DATE_MODIFIED,
                MediaStore.MediaColumns.RELATIVE_PATH
            )
            
            val manualBackupPattern = Regex("^workout_backup_.*\\.json$", RegexOption.IGNORE_CASE)
            val files = mutableListOf<BackupFileEntry>()
            
            fun queryCollection(
                collectionUri: android.net.Uri,
                limitToDownloads: Boolean,
                restrictToOwner: Boolean
            ): List<BackupFileEntry> {
                val foundFiles = mutableListOf<BackupFileEntry>()
                val baseSelectionParts = mutableListOf<String>()
                val baseSelectionArgs = mutableListOf<String>()
                
                if (restrictToOwner && android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.Q) {
                    baseSelectionParts.add("${MediaStore.MediaColumns.OWNER_PACKAGE_NAME} = ?")
                    baseSelectionArgs.add(context.packageName)
                }
                
                if (limitToDownloads) {
                    baseSelectionParts.add("${MediaStore.MediaColumns.RELATIVE_PATH} LIKE ?")
                    baseSelectionArgs.add("${Environment.DIRECTORY_DOWNLOADS}/%")
                }
                
                val allSelection = if (baseSelectionParts.isEmpty()) {
                    null
                } else {
                    baseSelectionParts.joinToString(" AND ")
                }
                val allSelectionArgs = if (baseSelectionArgs.isEmpty()) {
                    null
                } else {
                    baseSelectionArgs.toTypedArray()
                }
                
                resolver.query(
                    collectionUri,
                    projection,
                    allSelection,
                    allSelectionArgs,
                    "${MediaStore.MediaColumns.DATE_MODIFIED} DESC"
                )?.use { cursor ->
                    val idIndex = cursor.getColumnIndexOrThrow(MediaStore.MediaColumns._ID)
                    val nameIndex = cursor.getColumnIndexOrThrow(MediaStore.MediaColumns.DISPLAY_NAME)
                    val dateIndex = cursor.getColumnIndexOrThrow(MediaStore.MediaColumns.DATE_MODIFIED)
                    while (cursor.moveToNext()) {
                        val id = cursor.getLong(idIndex)
                        val name = cursor.getString(nameIndex)
                        val dateModified = cursor.getLong(dateIndex)
                        if (manualBackupPattern.matches(name)) {
                            foundFiles.add(
                                BackupFileEntry(
                                    ContentUris.withAppendedId(collectionUri, id),
                                    name,
                                    dateModified
                                )
                            )
                        }
                    }
                }
                
                return foundFiles
            }
            
            // Try Downloads first
            val downloadsFiles = queryCollection(
                MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                limitToDownloads = false,
                restrictToOwner = true
            )
            
            val downloadsFallbackFiles = if (downloadsFiles.isEmpty()) {
                queryCollection(
                    MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                    limitToDownloads = false,
                    restrictToOwner = false
                )
            } else {
                emptyList()
            }
            
            val resolvedDownloadsFiles = if (downloadsFiles.isEmpty()) {
                downloadsFallbackFiles
            } else {
                downloadsFiles
            }
            
            val filesCollectionFiles = if (resolvedDownloadsFiles.isEmpty()) {
                queryCollection(
                    MediaStore.Files.getContentUri(MediaStore.VOLUME_EXTERNAL),
                    limitToDownloads = true,
                    restrictToOwner = false
                )
            } else {
                emptyList()
            }
            
            (resolvedDownloadsFiles + filesCollectionFiles).distinctBy { it.uri }
        } catch (e: Exception) {
            Log.e("Utils", "Error finding manual backup files", e)
            emptyList()
        }
    }
}

/**
 * Reads file bytes from a URI.
 * Returns null if the file can't be read.
 */
private suspend fun readFileBytes(context: Context, uri: android.net.Uri): ByteArray? {
    return withContext(Dispatchers.IO) {
        try {
            context.contentResolver.openInputStream(uri)?.use { inputStream ->
                inputStream.readBytes()
            }
        } catch (e: Exception) {
            Log.e("Utils", "Error reading file bytes from URI: $uri", e)
            null
        }
    }
}

/**
 * Calculates SHA-256 hash of byte array.
 * Returns hex string representation of the hash.
 */
private fun calculateContentHash(bytes: ByteArray): String {
    val digest = MessageDigest.getInstance("SHA-256")
    val hashBytes = digest.digest(bytes)
    return hashBytes.joinToString("") { "%02x".format(it) }
}

/**
 * Creates an AppBackup from the current workout store and database state.
 * This is a helper function that extracts the backup creation logic.
 */
suspend fun createAppBackup(workoutStore: WorkoutStore, db: AppDatabase): AppBackup? {
    return withContext(Dispatchers.IO + NonCancellable) {
        try {
            // Get all DAOs
            val workoutHistoryDao = db.workoutHistoryDao()
            val setHistoryDao = db.setHistoryDao()
            val exerciseInfoDao = db.exerciseInfoDao()
            val workoutScheduleDao = db.workoutScheduleDao()
            val workoutRecordDao = db.workoutRecordDao()
            val exerciseSessionProgressionDao = db.exerciseSessionProgressionDao()
            val errorLogDao = db.errorLogDao()

            // Get all workout histories
            val workoutHistories = workoutHistoryDao.getAllWorkoutHistories()

            // Filter workouts: only active ones or ones with histories
            val allowedWorkouts = workoutStore.workouts.filter { workout ->
                workout.isActive || (!workout.isActive && workoutHistories.any { it.workoutId == workout.id })
            }

            // Filter workout histories by allowed workouts only
            val validWorkoutHistories = workoutHistories.filter { workoutHistory ->
                allowedWorkouts.any { workout -> workout.id == workoutHistory.workoutId }
            }

            // Filter set histories to match valid workout histories
            val setHistories = setHistoryDao.getAllSetHistories().filter { setHistory ->
                validWorkoutHistories.any { it.id == setHistory.workoutHistoryId }
            }

            // Get all exercise infos, workout schedules, workout records
            val exerciseInfos = exerciseInfoDao.getAllExerciseInfos()
            val workoutSchedules = workoutScheduleDao.getAllSchedules()
            val workoutRecords = workoutRecordDao.getAll()

            // Filter exercise session progressions to match valid workout histories
            val exerciseSessionProgressions = exerciseSessionProgressionDao.getAllExerciseSessionProgressions().filter { progression ->
                validWorkoutHistories.any { it.id == progression.workoutHistoryId }
            }

            // Get all error logs
            val errorLogs = errorLogDao.getAllErrorLogs().first()

            // Create AppBackup
            val appBackup = AppBackup(
                workoutStore.copy(workouts = allowedWorkouts),
                validWorkoutHistories,
                setHistories,
                exerciseInfos,
                workoutSchedules,
                workoutRecords,
                exerciseSessionProgressions,
                errorLogs.takeIf { it.isNotEmpty() }
            )

            // Check if AppBackup has any data before returning
            val hasData = appBackup.WorkoutStore.workouts.isNotEmpty() ||
                    appBackup.WorkoutHistories.isNotEmpty() ||
                    appBackup.SetHistories.isNotEmpty() ||
                    appBackup.ExerciseInfos.isNotEmpty() ||
                    appBackup.WorkoutSchedules.isNotEmpty() ||
                    appBackup.WorkoutRecords.isNotEmpty() ||
                    appBackup.ExerciseSessionProgressions.isNotEmpty() ||
                    run {
                        val errorLogs = appBackup.ErrorLogs
                        errorLogs != null && errorLogs.isNotEmpty()
                    }

            if (!hasData) {
                Log.d("Utils", "Skipping backup - no data to save")
                return@withContext null
            }

            appBackup
        } catch (e: Exception) {
            when (e) {
                is CancellationException -> {
                    Log.e("Utils", "Error creating AppBackup: Job was cancelled. " +
                            "Message: ${e.message}, " +
                            "Cause: ${e.cause?.javaClass?.simpleName ?: "none"}, " +
                            "Stack trace:\n${Log.getStackTraceString(e)}", e)
                }
                else -> {
                    Log.e("Utils", "Error creating AppBackup: ${e.javaClass.simpleName}. " +
                            "Message: ${e.message}, " +
                            "Cause: ${e.cause?.javaClass?.simpleName ?: "none"}, " +
                            "Stack trace:\n${Log.getStackTraceString(e)}", e)
                }
            }
            null
        }
    }
}

/**
 * Saves workout store to both internal storage and backup file.
 * This is a convenience function that combines both save operations.
 */
suspend fun saveWorkoutStoreWithBackup(
    context: Context,
    workoutStore: WorkoutStore,
    workoutStoreRepository: WorkoutStoreRepository,
    db: AppDatabase
) {
    withContext(Dispatchers.IO) {
        workoutStoreRepository.saveWorkoutStore(workoutStore)
        saveWorkoutStoreToExternalStorage(context, workoutStore, db)
    }
}

/**
 * Saves workout store with backup, automatically creating database and repository instances.
 * Use this in composables where you only have access to context.
 */
suspend fun saveWorkoutStoreWithBackupFromContext(
    context: Context,
    workoutStore: WorkoutStore
) {
    withContext(Dispatchers.IO) {
        val db = AppDatabase.getDatabase(context)
        val workoutStoreRepository = WorkoutStoreRepository(context.filesDir)
        workoutStoreRepository.saveWorkoutStore(workoutStore)
        saveWorkoutStoreToExternalStorage(context, workoutStore, db)
    }
}

/**
 * Cleans up duplicate backup files in Downloads folder.
 * This should be called once at app startup to remove any duplicate files that may have been created.
 * Keeps only the file with the exact name "workout_store_backup.json" if it exists, or the most recent one.
 */
suspend fun cleanupDuplicateBackupFiles(context: Context) {
    withContext(Dispatchers.IO) {
        try {
            fun showCleanupToast(message: String) {
                android.os.Handler(android.os.Looper.getMainLooper()).post {
                    Toast.makeText(context, message, Toast.LENGTH_SHORT).show()
                }
            }

            val downloadsPath = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS).absolutePath
            val folderLabel = "${Environment.DIRECTORY_DOWNLOADS} (MediaStore): $downloadsPath"
            val backupFileName = "workout_store_backup.json"
            val resolver = context.contentResolver

            Log.d("Utils", "Backup cleanup started in $folderLabel")
            
            // Find all existing files matching the backup pattern
            val allBackupFiles = findAllBackupFilesInDownloadsFolder(context, backupFileName)
            
            if (allBackupFiles.isEmpty()) {
                Log.d("Utils", "No backup files found to clean up")
                return@withContext
            }
            
            if (allBackupFiles.size == 1) {
                Log.d("Utils", "Only one backup file found, no cleanup needed")
                return@withContext
            }
            
            Log.d("Utils", "Found ${allBackupFiles.size} backup files, cleaning up duplicates")
            
            // Find the file with exact name match, or use the most recent one
            val exactMatch = allBackupFiles.firstOrNull { it.name == backupFileName }
            val targetFile = exactMatch ?: allBackupFiles.maxByOrNull { it.dateModified } ?: allBackupFiles.first()
            val targetUri = targetFile.uri
            
            // Delete all other files
            var deletedCount = 0
            for (file in allBackupFiles) {
                if (file.uri == targetUri) continue
                
                // Optionally check if content matches before deleting
                // (if content differs, we might want to keep it, but for cleanup we'll delete duplicates)
                try {
                    val deleted = deleteBackupFile(context, file.uri)
                    if (deleted) {
                        deletedCount++
                        Log.d("Utils", "Deleted duplicate backup file: ${file.name}")
                    } else {
                        Log.w("Utils", "No rows deleted for duplicate backup file: ${file.name}")
                    }
                } catch (e: Exception) {
                    Log.w("Utils", "Failed to delete duplicate backup file: ${file.name}", e)
                }
            }
            
            Log.d("Utils", "Cleanup complete: deleted $deletedCount duplicate backup file(s), kept: ${targetFile.name}")
            if (deletedCount > 0) {
                showCleanupToast("Deleted $deletedCount duplicate backup file(s)")
            }
        } catch (e: Exception) {
            Log.e("Utils", "Error cleaning up duplicate backup files", e)
        }
    }
}

/**
 * Cleans up duplicate backup files by comparing content hashes.
 * Finds all backup files (both automatic and manual patterns), groups them by content hash,
 * and keeps only the most recent file from each unique content group.
 * This ensures that files with identical content are deduplicated while preserving unique versions.
 */
suspend fun cleanupDuplicateBackupFilesByContent(context: Context) {
    withContext(Dispatchers.IO) {
        try {
            fun showCleanupToast(message: String) {
                android.os.Handler(android.os.Looper.getMainLooper()).post {
                    Toast.makeText(context, message, Toast.LENGTH_SHORT).show()
                }
            }

            Log.d("Utils", "Content-based backup cleanup started")
            
            // Find all backup files (both automatic and manual patterns)
            val allBackupFiles = findAllBackupFiles(context)
            
            if (allBackupFiles.isEmpty()) {
                Log.d("Utils", "No backup files found to clean up")
                return@withContext
            }
            
            if (allBackupFiles.size == 1) {
                Log.d("Utils", "Only one backup file found, no cleanup needed")
                return@withContext
            }
            
            Log.d("Utils", "Found ${allBackupFiles.size} backup files, analyzing content for duplicates")
            
            // Read bytes and calculate hash for each file
            val fileHashes = mutableMapOf<String, MutableList<BackupFileEntry>>()
            
            for (file in allBackupFiles) {
                try {
                    val bytes = readFileBytes(context, file.uri)
                    if (bytes == null) {
                        Log.w("Utils", "Failed to read bytes from file: ${file.name}, skipping")
                        continue
                    }
                    
                    // Skip empty files
                    if (bytes.isEmpty()) {
                        Log.w("Utils", "File is empty: ${file.name}, skipping")
                        continue
                    }
                    
                    val hash = calculateContentHash(bytes)
                    fileHashes.getOrPut(hash) { mutableListOf() }.add(file)
                    Log.d("Utils", "File: ${file.name}, hash: ${hash.take(16)}..., size: ${bytes.size} bytes")
                } catch (e: Exception) {
                    Log.w("Utils", "Error processing file ${file.name}, skipping", e)
                }
            }
            
            // Group files by hash and identify duplicates
            var totalDuplicates = 0
            var deletedCount = 0
            
            for ((hash, files) in fileHashes) {
                if (files.size > 1) {
                    // Multiple files with same content - keep only the most recent
                    val sortedFiles = files.sortedByDescending { it.dateModified }
                    val fileToKeep = sortedFiles.first()
                    val duplicatesToDelete = sortedFiles.drop(1)
                    
                    totalDuplicates += duplicatesToDelete.size
                    Log.d("Utils", "Found ${duplicatesToDelete.size} duplicate(s) of ${fileToKeep.name} (hash: ${hash.take(16)}...), keeping most recent: ${fileToKeep.name}")
                    
                    for (duplicate in duplicatesToDelete) {
                        try {
                            val deleted = deleteBackupFile(context, duplicate.uri)
                            if (deleted) {
                                deletedCount++
                                Log.d("Utils", "Deleted duplicate backup file: ${duplicate.name} (same content as ${fileToKeep.name})")
                            } else {
                                Log.w("Utils", "No rows deleted for duplicate backup file: ${duplicate.name}")
                            }
                        } catch (e: Exception) {
                            Log.w("Utils", "Failed to delete duplicate backup file: ${duplicate.name}", e)
                        }
                    }
                } else {
                    // Single file with this content - keep it
                    Log.d("Utils", "File ${files.first().name} has unique content (hash: ${hash.take(16)}...), keeping")
                }
            }
            
            val uniqueFiles = fileHashes.size
            Log.d("Utils", "Cleanup complete: $uniqueFiles unique content(s), $totalDuplicates duplicate(s) found, $deletedCount deleted, ${allBackupFiles.size - deletedCount} kept")
            
            if (deletedCount > 0) {
                showCleanupToast("Deleted $deletedCount duplicate backup file(s), kept $uniqueFiles unique version(s)")
            } else if (totalDuplicates == 0) {
                Log.d("Utils", "No duplicates found - all backup files have unique content")
            }
        } catch (e: Exception) {
            Log.e("Utils", "Error cleaning up duplicate backup files by content", e)
        }
    }
}

/**
 * Saves workout store backup to Downloads folder (persists after app uninstall).
 * Creates an AppBackup (including database data) and saves it to workout_store_backup.json.
 * This file can be used for recovery if the main workout_store.json gets corrupted.
 * Uses Downloads folder via MediaStore so the backup persists after uninstall and is accessible via file managers.
 */
suspend fun saveWorkoutStoreToExternalStorage(
    context: Context,
    workoutStore: WorkoutStore,
    db: AppDatabase
) {
    withContext(Dispatchers.IO + NonCancellable) {
        backupFileWriteMutex.withLock {
            try {
                val appBackup = createAppBackup(workoutStore, db)
                if (appBackup == null) {
                    Log.d("Utils", "No data to backup, skipping backup")
                    return@withContext
                }

                val jsonString = fromAppBackupToJSONPrettyPrint(appBackup)
                val backupFileName = "workout_store_backup.json"
                
                // Save to Downloads folder (persists after uninstall)
                val resolver = context.contentResolver
                val contentValues = ContentValues().apply {
                    put(MediaStore.MediaColumns.DISPLAY_NAME, backupFileName)
                    put(MediaStore.MediaColumns.MIME_TYPE, "application/json")
                    put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
                }

                // Find ALL backup files (including any duplicates that might exist)
                val allBackupFiles = findAllBackupFilesInDownloadsFolder(context, backupFileName)
                
                // Find the target file to use (exact match preferred, or most recent)
                val exactMatch = allBackupFiles.firstOrNull { it.name == backupFileName }
                val targetFile = exactMatch ?: allBackupFiles.maxByOrNull { it.dateModified }
                val targetUri = targetFile?.uri
                
                // Check if content has changed by comparing with target file
                var shouldSave = true
                if (targetUri != null) {
                    // Read existing content and compare
                    val existingContent = readFileContentFromDownloadsFolder(context, targetUri)
                    if (existingContent != null && existingContent == jsonString) {
                        Log.d("Utils", "Backup content unchanged, skipping save")
                        shouldSave = false
                        
                        // Still clean up any other duplicates
                        if (allBackupFiles.size > 1) {
                            cleanupDuplicateBackupFiles(context)
                        }
                    }
                }

                if (!shouldSave) {
                    return@withContext
                }

                val targetSaveUri = if (targetUri != null) {
                    if (targetFile?.name != backupFileName) {
                        try {
                            val renameValues = ContentValues().apply {
                                put(MediaStore.MediaColumns.DISPLAY_NAME, backupFileName)
                            }
                            resolver.update(targetUri, renameValues, null, null)
                        } catch (e: Exception) {
                            Log.w("Utils", "Failed to normalize backup file name", e)
                        }
                    }
                    targetUri
                } else {
                    try {
                        resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, contentValues)
                    } catch (e: Exception) {
                        Log.e("Utils", "Failed to create backup file", e)
                        null
                    }
                }

                targetSaveUri?.let { uri ->
                    try {
                        // Write the content
                        val wroteContent = resolver.openOutputStream(uri, "wt")?.use { outputStream ->
                            outputStream.write(jsonString.toByteArray())
                            outputStream.flush()
                            true
                        } ?: false
                        if (wroteContent) {
                            Log.d("Utils", "Backup saved to Downloads folder: $backupFileName")
                            
                            // Final cleanup after save to catch any duplicates that might have been created
                            kotlinx.coroutines.delay(200) // Give MediaStore time to index
                            cleanupDuplicateBackupFiles(context)
                        } else {
                            Log.e("Utils", "Failed to open output stream for backup file")
                        }
                    } catch (e: Exception) {
                        Log.e("Utils", "Error writing to backup file", e)
                        // Try to clean up the failed file
                        try {
                            resolver.delete(uri, null, null)
                        } catch (deleteException: Exception) {
                            Log.e("Utils", "Error cleaning up failed file", deleteException)
                        }
                    }
                } ?: run {
                    Log.e("Utils", "Failed to create backup file in Downloads folder")
                }
                
                // Also try to migrate old backup from external files dir (one-time migration)
                try {
                    val externalDir = context.getExternalFilesDir(null)
                    val oldBackupFile = externalDir?.let { java.io.File(it, backupFileName) }
                    oldBackupFile?.takeIf { it.exists() }?.delete()
                    Log.d("Utils", "Cleaned up old backup file from external files dir")
                } catch (e: Exception) {
                    // Ignore migration errors
                    Log.d("Utils", "Could not clean up old backup file", e)
                }
            } catch (e: Exception) {
                when (e) {
                    is CancellationException -> {
                        Log.e("Utils", "Error saving workout store to external storage: Job was cancelled. " +
                                "Message: ${e.message}, " +
                                "Cause: ${e.cause?.javaClass?.simpleName ?: "none"}, " +
                                "Stack trace:\n${Log.getStackTraceString(e)}", e)
                    }
                    else -> {
                        Log.e("Utils", "Error saving workout store to external storage: ${e.javaClass.simpleName}. " +
                                "Message: ${e.message}, " +
                                "Cause: ${e.cause?.javaClass?.simpleName ?: "none"}, " +
                                "Stack trace:\n${Log.getStackTraceString(e)}", e)
                    }
                }
            }
        }
    }
}

/**
 * Checks if an external backup file exists.
 * Checks both Downloads folder (new location) and external files dir (old location).
 * Note: This is a synchronous check, so it only checks the old location for performance.
 * For accurate results including Downloads folder, use loadExternalBackup() and check for null.
 */
fun hasExternalBackup(context: Context): Boolean {
    // Check old location (external files dir) synchronously
    val externalDir = context.getExternalFilesDir(null)
    val oldBackupFile = externalDir?.let { java.io.File(it, "workout_store_backup.json") }
    if (oldBackupFile?.exists() == true) {
        return true
    }
    
    // Downloads folder check requires async MediaStore query, so we can't do it synchronously
    // The loadExternalBackup function will check both locations properly
    return false
}

/**
 * Loads the external backup file and parses it as AppBackup.
 * First tries Downloads folder (new location), then falls back to external files dir (old location).
 * Returns null if the file doesn't exist or parsing fails.
 */
suspend fun loadExternalBackup(context: Context): AppBackup? {
    return withContext(Dispatchers.IO) {
        try {
            val backupFileName = "workout_store_backup.json"
            
            // First try Downloads folder (new location - persists after uninstall)
            val jsonString = readJsonFromDownloadsFolder(context, backupFileName)
            if (jsonString != null) {
                try {
                    val appBackup = fromJSONtoAppBackup(jsonString)
                    Log.d("Utils", "Backup loaded successfully from Downloads folder")
                    return@withContext appBackup
                } catch (e: Exception) {
                    when (e) {
                        is CancellationException -> {
                            Log.e("Utils", "Error parsing backup from Downloads folder: Job was cancelled. " +
                                    "Message: ${e.message}, " +
                                    "Cause: ${e.cause?.javaClass?.simpleName ?: "none"}, " +
                                    "Stack trace:\n${Log.getStackTraceString(e)}", e)
                        }
                        else -> {
                            Log.e("Utils", "Error parsing backup from Downloads folder: ${e.javaClass.simpleName}. " +
                                    "Message: ${e.message}, " +
                                    "Cause: ${e.cause?.javaClass?.simpleName ?: "none"}, " +
                                    "Stack trace:\n${Log.getStackTraceString(e)}", e)
                        }
                    }
                    // Continue to fallback location
                }
            }
            
            // Fallback to old location (external files dir) for backward compatibility
            val externalDir = context.getExternalFilesDir(null)
            if (externalDir == null) {
                Log.d("Utils", "External storage not available and no backup in Downloads")
                return@withContext null
            }
            val backupFile = java.io.File(externalDir, backupFileName)
            if (!backupFile.exists()) {
                Log.d("Utils", "Backup file does not exist in either location")
                return@withContext null
            }

            val oldJsonString = backupFile.readText()
            val appBackup = fromJSONtoAppBackup(oldJsonString)
            Log.d("Utils", "Backup loaded successfully from old location (external files dir)")
            appBackup
        } catch (e: Exception) {
            when (e) {
                is CancellationException -> {
                    Log.e("Utils", "Error loading backup from external storage: Job was cancelled. " +
                            "Message: ${e.message}, " +
                            "Cause: ${e.cause?.javaClass?.simpleName ?: "none"}, " +
                            "Stack trace:\n${Log.getStackTraceString(e)}", e)
                }
                else -> {
                    Log.e("Utils", "Error loading backup from external storage: ${e.javaClass.simpleName}. " +
                            "Message: ${e.message}, " +
                            "Cause: ${e.cause?.javaClass?.simpleName ?: "none"}, " +
                            "Stack trace:\n${Log.getStackTraceString(e)}", e)
                }
            }
            null
        }
    }
}

suspend fun saveWorkoutStoreToDownloads(context: Context, workoutStore: WorkoutStore, db: AppDatabase) {
    withContext(Dispatchers.IO) {
        try {
            val resolver = context.contentResolver

            // Get all DAOs
            val workoutHistoryDao = db.workoutHistoryDao()
            val setHistoryDao = db.setHistoryDao()
            val exerciseInfoDao = db.exerciseInfoDao()
            val workoutScheduleDao = db.workoutScheduleDao()
            val workoutRecordDao = db.workoutRecordDao()
            val exerciseSessionProgressionDao = db.exerciseSessionProgressionDao()
            val errorLogDao = db.errorLogDao()

            // Get all workout histories
            val workoutHistories = workoutHistoryDao.getAllWorkoutHistories()

            // Filter workouts: only active ones or ones with histories
            val allowedWorkouts = workoutStore.workouts.filter { workout ->
                workout.isActive || (!workout.isActive && workoutHistories.any { it.workoutId == workout.id })
            }

            // Filter workout histories by allowed workouts only (original backup logic - no exercise-based filtering)
            val validWorkoutHistories = workoutHistories.filter { workoutHistory ->
                allowedWorkouts.any { workout -> workout.id == workoutHistory.workoutId }
            }

            // Filter set histories to match valid workout histories
            val setHistories = setHistoryDao.getAllSetHistories().filter { setHistory ->
                validWorkoutHistories.any { it.id == setHistory.workoutHistoryId }
            }

            // Get all exercise infos, workout schedules, workout records
            val exerciseInfos = exerciseInfoDao.getAllExerciseInfos()
            val workoutSchedules = workoutScheduleDao.getAllSchedules()
            val workoutRecords = workoutRecordDao.getAll()

            // Filter exercise session progressions to match valid workout histories
            val exerciseSessionProgressions = exerciseSessionProgressionDao.getAllExerciseSessionProgressions().filter { progression ->
                validWorkoutHistories.any { it.id == progression.workoutHistoryId }
            }

            // Get all error logs
            val errorLogs = errorLogDao.getAllErrorLogs().first()

            // Create AppBackup with the same structure as original manual backup
            val appBackup = AppBackup(
                workoutStore.copy(workouts = allowedWorkouts),
                validWorkoutHistories,
                setHistories,
                exerciseInfos,
                workoutSchedules,
                workoutRecords,
                exerciseSessionProgressions,
                errorLogs.takeIf { it.isNotEmpty() }
            )

            // Check if AppBackup has any data before saving
            val hasData = appBackup.WorkoutStore.workouts.isNotEmpty() ||
                    appBackup.WorkoutHistories.isNotEmpty() ||
                    appBackup.SetHistories.isNotEmpty() ||
                    appBackup.ExerciseInfos.isNotEmpty() ||
                    appBackup.WorkoutSchedules.isNotEmpty() ||
                    appBackup.WorkoutRecords.isNotEmpty() ||
                    appBackup.ExerciseSessionProgressions.isNotEmpty() ||
                    run {
                        val errorLogs = appBackup.ErrorLogs
                        errorLogs != null && errorLogs.isNotEmpty()
                    }

            if (!hasData) {
                Log.d("Utils", "Skipping backup - no data to save")
                return@withContext
            }

            val jsonString = fromAppBackupToJSONPrettyPrint(appBackup)

            // Helper function to try inserting a file with a given filename
            fun tryInsertFile(fileNameToTry: String): android.net.Uri? {
                val contentValues = ContentValues().apply {
                    put(MediaStore.MediaColumns.DISPLAY_NAME, fileNameToTry)
                    put(MediaStore.MediaColumns.MIME_TYPE, "application/json")
                    put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
                }

                return try {
                    resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, contentValues)
                } catch (e: IllegalStateException) {
                    // MediaStore couldn't create unique file, likely because file already exists
                    Log.w("Utils", "Failed to insert file with name $fileNameToTry: ${e.message}")
                    null
                } catch (e: Exception) {
                    Log.e("Utils", "Unexpected error inserting file with name $fileNameToTry", e)
                    null
                }
            }

            // Generate timestamp-based filename
            val sdf = java.text.SimpleDateFormat("yyyyMMdd_HHmmss", java.util.Locale.getDefault())
            val timestamp = sdf.format(java.util.Date())
            val fileName = "workout_store_$timestamp.json"

            // Try to insert file with timestamped name
            val uri = tryInsertFile(fileName)

            // Write the content if we successfully created the file
            if (uri != null) {
                try {
                    resolver.openOutputStream(uri)?.use { outputStream ->
                        outputStream.write(jsonString.toByteArray())
                        outputStream.flush()
                    } ?: run {
                        Log.e("Utils", "Failed to open output stream for backup file: $fileName")
                        // Clean up the failed file
                        try {
                            resolver.delete(uri, null, null)
                        } catch (deleteException: Exception) {
                            Log.e("Utils", "Error cleaning up failed file insert", deleteException)
                        }
                    }
                } catch (e: Exception) {
                    Log.e("Utils", "Error writing to backup file: $fileName", e)
                    // Try to clean up the failed insert
                    try {
                        resolver.delete(uri, null, null)
                    } catch (deleteException: Exception) {
                        Log.e("Utils", "Error cleaning up failed file insert", deleteException)
                    }
                }
            } else {
                Log.e("Utils", "Failed to create backup file - could not insert with filename: $fileName")
            }
        } catch (e: Exception) {
            Log.e("Utils", "Error saving workout store to Downloads folder", e)
        }
    }
}

suspend fun writeMarkdownToDownloadsFolder(context: Context, fileName: String, fileContent: String) {
    val contentValues = ContentValues().apply {
        put(MediaStore.MediaColumns.DISPLAY_NAME, fileName)
        put(MediaStore.MediaColumns.MIME_TYPE, "text/markdown")
        put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
    }

    val resolver = context.contentResolver
    val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, contentValues)

    uri?.let {
        resolver.openOutputStream(it).use { outputStream ->
            outputStream?.write(fileContent.toByteArray())
        }
        withContext(Dispatchers.Main) {
            Toast.makeText(context, "Export saved to downloads folder", Toast.LENGTH_SHORT).show()
        }
    } ?: run {
        withContext(Dispatchers.Main) {
            Toast.makeText(context, "Failed to write to downloads folder", Toast.LENGTH_SHORT).show()
        }
    }
}

fun Modifier.optionalClip(shape:RoundedCornerShape?): Modifier {
    return if (shape != null) {
        clip(shape)
    } else {
        this
    }
}

fun formatTime(seconds: Int): String {
    val hours = seconds / 3600
    val minutes = (seconds % 3600) / 60
    val remainingSeconds = seconds % 60
    return if (hours > 0) {
        String.format("%02d:%02d:%02d", hours, minutes, remainingSeconds)
    } else {
        String.format("%02d:%02d", minutes, remainingSeconds)
    }
}

fun formatTimeHourMinutes(seconds: Int): String {
    val hours = seconds / 3600
    val minutes = (seconds % 3600) / 60

    return String.format("%02d:%02d", hours, minutes)
}

fun getEnabledStatusOfWorkoutComponent(workoutComponent: WorkoutComponent): Boolean {
    return when (workoutComponent) {
        is Exercise -> workoutComponent.enabled
        is Rest -> workoutComponent.enabled
        is Superset -> workoutComponent.enabled
        else -> false // Default case if the component type is unknown
    }
}

fun getStartOfWeek(date: LocalDate): LocalDate {
    return date.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
}

fun getEndOfWeek(date: LocalDate): LocalDate {
    return date.with(TemporalAdjusters.nextOrSame(DayOfWeek.SUNDAY))
}

fun getOneRepMax(weight: Double, reps: Int): Double {
    return weight / (1.0278f - (0.0278f * reps))
}

fun calculateKiloCaloriesBurned(
    age: Int,
    weightKg: Double,
    averageHeartRate: Double,
    durationMinutes: Double,
    isMale: Boolean
): Double {
    if (age <= 0 || weightKg <= 0 || averageHeartRate <= 0 || durationMinutes <= 0) {
        return 0.0
    }

    val caloriesBurned = if (isMale) {
        (age * 0.2017) + (weightKg * 0.199) + (averageHeartRate * 0.6309) - 55.0969
    } else {
        (age * 0.074) - (weightKg * 0.05741) + (averageHeartRate * 0.4472) - 20.4022
    }

    return caloriesBurned * durationMinutes / 4.184
}

@SuppressLint("RestrictedApi")
suspend fun sendWorkoutsToHealthConnect(
    workouts: List<Workout>,
    healthConnectClient: HealthConnectClient,
    workoutHistoryDao: WorkoutHistoryDao,
    updateAll: Boolean = false,
    age: Int,
    weightKg: Double,
) {
    if (workouts.isEmpty()) return

    val requiredPermissions = setOf(
        HealthPermission.getReadPermission(ExerciseSessionRecord::class),
        HealthPermission.getWritePermission(ExerciseSessionRecord::class),
        HealthPermission.getReadPermission(HeartRateRecord::class),
        HealthPermission.getWritePermission(HeartRateRecord::class)
    )

    val grantedPermissions = healthConnectClient.permissionController.getGrantedPermissions()
    val missingPermissions = requiredPermissions - grantedPermissions

    if (missingPermissions.isNotEmpty()) {
        throw IllegalStateException("Missing required permissions: $missingPermissions")
    }

    val workoutsById = workouts.associateBy { it.id }

    val workoutHistories = if(updateAll){
        workoutHistoryDao.getAllWorkoutHistoriesByIsDone()
    }else {
        workoutHistoryDao.getWorkoutHistoriesByHasBeenSentToHealth(false)
    }.filter { workoutsById.containsKey(it.workoutId) }

    if (workoutHistories.isEmpty()) return

    // Process workout histories in batches of 5 to avoid exceeding Health Connect's 5MB chunk limit
    val batchSize = 5
    workoutHistories.chunked(batchSize).forEach { batch ->
        // Delete existing records for this batch
        healthConnectClient.deleteRecords(
            ExerciseSessionRecord::class,
            clientRecordIdsList = batch.map { it.id.toString() },
            recordIdsList = emptyList()
        )

        healthConnectClient.deleteRecords(
            HeartRateRecord::class,
            clientRecordIdsList = batch.map { it.id.toString() },
            recordIdsList = emptyList()
        )

        healthConnectClient.deleteRecords(
            TotalCaloriesBurnedRecord::class,
            clientRecordIdsList = batch.map { it.id.toString() },
            recordIdsList = emptyList()
        )

        // Create records for this batch
        val exerciseSessionRecords = batch.map {
            ExerciseSessionRecord(
                startTime = it.startTime.atZone(ZoneId.systemDefault()).toInstant(),
                startZoneOffset = ZoneOffset.systemDefault().rules.getOffset(Instant.now()),
                endTime = it.startTime.plusSeconds(it.duration.toLong())
                    .atZone(ZoneId.systemDefault()).toInstant(),

                endZoneOffset = ZoneOffset.systemDefault().rules.getOffset(Instant.now()),
                exerciseType = workoutsById[it.workoutId]!!.type,
                title = workoutsById[it.workoutId]!!.name,
                metadata = Metadata.activelyRecorded(
                    Device(type = Device.TYPE_WATCH),
                    clientRecordId = it.id.toString()
                ),
            )
        }

        val heartRateRecords = batch
            .filter { it.heartBeatRecords.isNotEmpty() }
            .mapNotNull { workoutHistory ->
                val startTime = workoutHistory.startTime.atZone(ZoneId.systemDefault()).toInstant()
                val endTime = workoutHistory.startTime.plusSeconds(workoutHistory.duration.toLong()).atZone(ZoneId.systemDefault()).toInstant()
                val zoneOffset = ZoneOffset.systemDefault().rules.getOffset(Instant.now())

                val samples = workoutHistory.heartBeatRecords.mapIndexedNotNull { index, bpm ->
                    val sampleTime = startTime.plus(Duration.ofMillis(index.toLong() * 1000))
                    if (sampleTime.isAfter(endTime) || bpm <= 0) {
                        null
                    } else {
                        HeartRateRecord.Sample(
                            time = sampleTime,
                            beatsPerMinute = bpm.toLong()
                        )
                    }
                }

                if(samples.isEmpty()) {
                    return@mapNotNull null
                }

                HeartRateRecord(
                    startTime = startTime,
                    endTime = endTime,
                    startZoneOffset = zoneOffset,
                    endZoneOffset = zoneOffset,
                    samples = samples,
                    metadata = Metadata.activelyRecorded(
                        Device(type = Device.TYPE_WATCH),
                        clientRecordId =   workoutHistory.id.toString()
                    )
                )
            }

        val totalCaloriesBurnedRecords = batch
            .filter { it.heartBeatRecords.isNotEmpty() }
            .mapNotNull { workoutHistory ->
                val avgHeartRate = workoutHistory.heartBeatRecords.average()

                val durationMinutes = workoutHistory.duration.toDouble() / 60
                val kiloCaloriesBurned = calculateKiloCaloriesBurned(
                    age = age,
                    weightKg = weightKg.toDouble(),
                    averageHeartRate = avgHeartRate,
                    durationMinutes = durationMinutes,
                    isMale = true
                )

                if(kiloCaloriesBurned <= 0) {
                    return@mapNotNull null
                }

                val startTime = workoutHistory.startTime.atZone(ZoneId.systemDefault()).toInstant()
                val endTime = workoutHistory.startTime.plusSeconds(workoutHistory.duration.toLong()).atZone(ZoneId.systemDefault()).toInstant()
                val zoneOffset = ZoneOffset.systemDefault().rules.getOffset(Instant.now())

                androidx.health.connect.client.records.TotalCaloriesBurnedRecord(
                    startTime= startTime,
                    startZoneOffset = zoneOffset,
                    endTime = endTime,
                    endZoneOffset = zoneOffset,
                    energy = Energy.kilocalories(kiloCaloriesBurned),
                    metadata =  Metadata.activelyRecorded(
                        Device(type = Device.TYPE_WATCH),
                        clientRecordId = workoutHistory.id.toString()
                    )
                )
            }

        // Insert records for this batch
        healthConnectClient.insertRecords(exerciseSessionRecords)
        healthConnectClient.insertRecords(heartRateRecords)
        healthConnectClient.insertRecords(totalCaloriesBurnedRecords)

        // Update hasBeenSentToHealth flag for this batch
        for (workoutHistory in batch) {
            workoutHistoryDao.updateHasBeenSentToHealth(workoutHistory.id, true)
        }
    }
}

@SuppressLint("RestrictedApi")
suspend fun deleteWorkoutHistoriesFromHealthConnect(
    workoutHistories: List<WorkoutHistory>,
    healthConnectClient: HealthConnectClient
) {
    if (workoutHistories.isEmpty()) return

    val requiredPermissions = setOf(
        HealthPermission.getReadPermission(ExerciseSessionRecord::class),
        HealthPermission.getWritePermission(ExerciseSessionRecord::class),
        HealthPermission.getReadPermission(HeartRateRecord::class),
        HealthPermission.getWritePermission(HeartRateRecord::class)
    )

    val grantedPermissions = healthConnectClient.permissionController.getGrantedPermissions()
    val missingPermissions = requiredPermissions - grantedPermissions

    if (missingPermissions.isNotEmpty()) {
        throw IllegalStateException("Missing required permissions: $missingPermissions")
    }

    healthConnectClient.deleteRecords(
        ExerciseSessionRecord::class,
        clientRecordIdsList = workoutHistories.map { it.id.toString() },
        recordIdsList = emptyList()
    )

    healthConnectClient.deleteRecords(
        HeartRateRecord::class,
        clientRecordIdsList = workoutHistories.map { it.id.toString() },
        recordIdsList = emptyList()
    )

    healthConnectClient.deleteRecords(
        TotalCaloriesBurnedRecord::class,
        clientRecordIdsList = workoutHistories.map { it.id.toString() },
        recordIdsList = emptyList()
    )
}

fun calculateVolume(weight: Double, reps: Int): Double {
    if(weight == 0.0) return reps.toDouble()
    return weight * reps
}

fun calculateOneRepMax(weight: Double, reps: Int): Double =
    weight * reps.toDouble().pow(0.10)

fun Double.round(decimals: Int): Double {
    var multiplier = 1.0
    repeat(decimals) { multiplier *= 10 }
    return kotlin.math.round(this * multiplier) / multiplier
}

fun Float.round(decimals: Int): Float {
    var multiplier = 1.0f
    repeat(decimals) { multiplier *= 10 }
    return kotlin.math.round(this * multiplier) / multiplier
}

// Default height for the content fade gradient
private val DEFAULT_CONTENT_FADE_HEIGHT = 10.dp

@Composable
fun Modifier.verticalColumnScrollbar(
    scrollState: ScrollState,
    width: Dp = 4.dp,
    showScrollBarTrack: Boolean = true,
    scrollBarTrackColor: Color? = null,
    scrollBarColor: Color? = null,
    scrollBarCornerRadius: Float = 4f,
    endPadding: Float = 12f,
    trackHeight: Dp? = null,
    maxThumbHeightFraction: Float = 0.75f,      // Maximum thumb height as fraction of track height (0.0..1.0)
    // Content fade effect parameters
    enableTopFade: Boolean = false,
    enableBottomFade: Boolean = false,
    contentFadeHeight: Dp = DEFAULT_CONTENT_FADE_HEIGHT,
    contentFadeColor: Color? = null
): Modifier {
    val defaultTrackColor = scrollBarTrackColor ?: MediumDarkGray
    val defaultScrollBarColor = scrollBarColor ?: MaterialTheme.colorScheme.onBackground
    val defaultFadeColor = contentFadeColor ?: MaterialTheme.colorScheme.background
    // Remember updated state for all parameters accessed within draw lambda
    val rememberedShowTrack by rememberUpdatedState(showScrollBarTrack)
    val rememberedTrackColor by rememberUpdatedState(defaultTrackColor)
    val rememberedScrollBarColor by rememberUpdatedState(defaultScrollBarColor)
    val rememberedWidth by rememberUpdatedState(width)
    val rememberedCornerRadius by rememberUpdatedState(scrollBarCornerRadius)
    val rememberedEndPadding by rememberUpdatedState(endPadding)
    val rememberedTrackHeight by rememberUpdatedState(trackHeight)
    val rememberedEnableTopFade by rememberUpdatedState(enableTopFade)
    val rememberedEnableBottomFade by rememberUpdatedState(enableBottomFade)
    val rememberedContentFadeHeight by rememberUpdatedState(contentFadeHeight)
    val rememberedContentFadeColor by rememberUpdatedState(defaultFadeColor)
    val rememberedMaxThumbHeightFraction by rememberUpdatedState(maxThumbHeightFraction)

    // State for scrollbar visibility
    var scrollbarVisible by remember { mutableStateOf(false) }
    var hideTimeoutJob by remember { mutableStateOf<Job?>(null) }
    val coroutineScope = rememberCoroutineScope()

    // Animate scrollbar opacity
    val scrollbarAlpha by animateFloatAsState(
        targetValue = if (scrollbarVisible) 1f else 0f,
        animationSpec = tween(durationMillis = 250),
        label = "scrollbar_fade"
    )

    // Show scrollbar on scroll interaction
    LaunchedEffect(scrollState.value) {
        scrollbarVisible = true
        hideTimeoutJob?.cancel()
        hideTimeoutJob = coroutineScope.launch {
            delay(2500) // 2.5 seconds
            scrollbarVisible = false
        }
    }

    return this
        .pointerInput(Unit) {
            detectTapGestures {
                scrollbarVisible = true
                hideTimeoutJob?.cancel()
                hideTimeoutJob = coroutineScope.launch {
                    delay(2500)
                    scrollbarVisible = false
                }
            }
        }
        .drawWithContent {
        // --- Draw the actual content first ---
        drawContent()

        // --- Content Fade Logic ---
        val fadeHeightPx = rememberedContentFadeHeight.toPx()
        val componentWidth = size.width
        val componentHeight = size.height
        val currentScrollValue = scrollState.value.toFloat()
        val maxScrollValue = scrollState.maxValue.toFloat()

        // Only proceed with fade drawing if fade height is positive
        if (fadeHeightPx > 0f) {

            // --- Top Fade Calculation ---
            if (rememberedEnableTopFade) {
                // Calculate alpha based on proximity to the top edge (within fadeHeightPx)
                // Alpha is 0.0 when scrollValue is 0, 1.0 when scrollValue >= fadeHeightPx
                val topAlpha = (currentScrollValue / fadeHeightPx).coerceIn(0f, 1f)

                // Only draw if alpha is > 0 (i.e., not exactly at the top)
                if (topAlpha > 0f) {
                    val topFadeBrush = Brush.verticalGradient(
                        colors = listOf(rememberedContentFadeColor, Color.Transparent),
                        startY = 0f,
                        endY = fadeHeightPx.coerceAtMost(componentHeight)
                    )
                    drawRect(
                        brush = topFadeBrush,
                        alpha = topAlpha,
                        topLeft = Offset.Zero,
                        size = Size(componentWidth, fadeHeightPx.coerceAtMost(componentHeight))
                    )
                }
            }

            // --- Bottom Fade Calculation ---
            if (rememberedEnableBottomFade && maxScrollValue > 0) { // Also check if scrolling is possible at all
                // Calculate distance from the bottom edge
                val distanceToBottom = maxScrollValue - currentScrollValue

                // Calculate alpha based on proximity to the bottom edge (within fadeHeightPx)
                // Alpha is 0.0 when distance is 0 (at bottom), 1.0 when distance >= fadeHeightPx
                val bottomAlpha = (distanceToBottom / fadeHeightPx).coerceIn(0f, 1f)

                // Only draw if alpha is > 0 (i.e., not exactly at the bottom)
                if (bottomAlpha > 0f) {
                    val bottomFadeBrush = Brush.verticalGradient(
                        colors = listOf(Color.Transparent, rememberedContentFadeColor),
                        startY = (componentHeight - fadeHeightPx).coerceAtLeast(0f),
                        endY = componentHeight
                    )
                    drawRect(
                        brush = bottomFadeBrush,
                        alpha = bottomAlpha,
                        topLeft = Offset(0f, (componentHeight - fadeHeightPx).coerceAtLeast(0f)),
                        size = Size(componentWidth, fadeHeightPx.coerceAtMost(componentHeight))
                    )
                }
            }
        }


        // --- Scrollbar Logic (remains the same, drawn on top) ---
        val viewportHeight = componentHeight
        val totalContentHeight = (maxScrollValue + viewportHeight).coerceAtLeast(viewportHeight)
        val scrollValue = currentScrollValue // Use already fetched value
        val visibleRatio = (viewportHeight / totalContentHeight).coerceIn(0f, 1f)

        if (visibleRatio >= 1f || maxScrollValue <= 0) {
            return@drawWithContent
        }

        val defaultTrackHeight = viewportHeight
        val actualTrackHeight = rememberedTrackHeight?.toPx()?.coerceAtMost(viewportHeight) ?: defaultTrackHeight
        val trackTopOffset = if (actualTrackHeight < viewportHeight) {
            (viewportHeight - actualTrackHeight) / 2f
        } else {
            0f
        }

        val minThumbHeight = rememberedWidth.toPx() * 2
        val scrollBarHeight = (visibleRatio * actualTrackHeight)
            .coerceAtLeast(minThumbHeight)
            .coerceAtMost(actualTrackHeight)
        val availableScrollSpace = maxScrollValue
        val availableTrackSpace = (actualTrackHeight - scrollBarHeight).coerceAtLeast(0f)
        val scrollProgress = if (availableScrollSpace > 0) scrollValue / availableScrollSpace else 0f
        val clampedScrollProgress = scrollProgress.coerceIn(0f, 1f)
        val scrollBarOffsetWithinTrack = clampedScrollProgress * availableTrackSpace
        val scrollBarTopOffset = trackTopOffset + scrollBarOffsetWithinTrack

        val cornerRadius = CornerRadius(rememberedCornerRadius)
        val barWidthPx = rememberedWidth.toPx()
        val paddingPx = rememberedEndPadding

        // Only draw scrollbar if alpha > 0
        if (scrollbarAlpha > 0f) {
            if (rememberedShowTrack) {
                drawRoundRect(
                    color = rememberedTrackColor.copy(alpha = scrollbarAlpha),
                    topLeft = Offset(componentWidth - paddingPx - barWidthPx, trackTopOffset),
                    size = Size(barWidthPx, actualTrackHeight),
                    cornerRadius = cornerRadius
                )
            }

            drawRoundRect(
                color = rememberedScrollBarColor.copy(alpha = scrollbarAlpha),
                topLeft = Offset(componentWidth - paddingPx - barWidthPx, scrollBarTopOffset),
                size = Size(barWidthPx, scrollBarHeight),
                cornerRadius = cornerRadius
            )
        }
    }
}

@Composable
fun Modifier.verticalLazyColumnScrollbar(
    lazyListState: LazyListState,
    width: Dp = 4.dp,
    showScrollBarTrack: Boolean = true,
    scrollBarTrackColor: Color? = null,
    scrollBarColor: Color? = null,
    scrollBarCornerRadius: Float = 4f,
    endPadding: Float = 12f,
    trackHeight: Dp? = null,
    maxThumbHeightFraction: Float = 0.75f,      // Maximum thumb height as fraction of track height (0.0..1.0)
    // Content fade effect parameters
    enableTopFade: Boolean = false,
    enableBottomFade: Boolean = false,
    contentFadeHeight: Dp = DEFAULT_CONTENT_FADE_HEIGHT,
    contentFadeColor: Color? = null
): Modifier {
    val defaultTrackColor = scrollBarTrackColor ?: MediumDarkGray
    val defaultScrollBarColor = scrollBarColor ?: MaterialTheme.colorScheme.onSurfaceVariant
    val defaultFadeColor = contentFadeColor ?: MaterialTheme.colorScheme.background
    val rememberedShowTrack by rememberUpdatedState(showScrollBarTrack)
    val rememberedTrackColor by rememberUpdatedState(defaultTrackColor)
    val rememberedScrollBarColor by rememberUpdatedState(defaultScrollBarColor)
    val rememberedWidth by rememberUpdatedState(width)
    val rememberedCornerRadius by rememberUpdatedState(scrollBarCornerRadius)
    val rememberedEndPadding by rememberUpdatedState(endPadding)
    val rememberedTrackHeight by rememberUpdatedState(trackHeight)
    val rememberedEnableTopFade by rememberUpdatedState(enableTopFade)
    val rememberedEnableBottomFade by rememberUpdatedState(enableBottomFade)
    val rememberedContentFadeHeight by rememberUpdatedState(contentFadeHeight)
    val rememberedContentFadeColor by rememberUpdatedState(defaultFadeColor)
    val rememberedMaxThumbHeightFraction by rememberUpdatedState(maxThumbHeightFraction)

    // State for scrollbar visibility
    var scrollbarVisible by remember { mutableStateOf(false) }
    var hideTimeoutJob by remember { mutableStateOf<Job?>(null) }
    val coroutineScope = rememberCoroutineScope()

    // Animate scrollbar opacity
    val scrollbarAlpha by animateFloatAsState(
        targetValue = if (scrollbarVisible) 1f else 0f,
        animationSpec = tween(durationMillis = 250),
        label = "scrollbar_fade"
    )

    val layoutInfo = lazyListState.layoutInfo
    val visibleItemsInfo = layoutInfo.visibleItemsInfo

    // Show scrollbar on scroll interaction - use firstVisibleItemIndex to track scroll changes
    val firstVisibleItemIndex = visibleItemsInfo.firstOrNull()?.index ?: 0
    LaunchedEffect(firstVisibleItemIndex, lazyListState.firstVisibleItemScrollOffset) {
        scrollbarVisible = true
        hideTimeoutJob?.cancel()
        hideTimeoutJob = coroutineScope.launch {
            delay(2500) // 2.5 seconds
            scrollbarVisible = false
        }
    }

    return this
        .pointerInput(Unit) {
            detectTapGestures {
                scrollbarVisible = true
                hideTimeoutJob?.cancel()
                hideTimeoutJob = coroutineScope.launch {
                    delay(2500)
                    scrollbarVisible = false
                }
            }
        }
        .drawWithContent {
        drawContent()

        val componentWidth = size.width
        val componentHeight = size.height
        val viewportHeight = componentHeight.toFloat()

        // Calculate scroll position and total content height
        val firstVisibleItem = visibleItemsInfo.firstOrNull()
        
        if (firstVisibleItem == null || layoutInfo.totalItemsCount == 0) {
            return@drawWithContent
        }

        // Calculate current scroll position (pixels scrolled)
        val currentScrollValue = if (firstVisibleItem.index > 0) {
            // Estimate: sum of heights of items before first visible item
            // Use average item height from visible items as estimate
            val avgItemHeight = if (visibleItemsInfo.isNotEmpty()) {
                visibleItemsInfo.sumOf { it.size }.toFloat() / visibleItemsInfo.size
            } else {
                firstVisibleItem.size.toFloat()
            }
            (firstVisibleItem.index * avgItemHeight) - firstVisibleItem.offset
        } else {
            (-firstVisibleItem.offset).toFloat()
        }

        // Calculate total content height
        // Estimate based on visible items and total item count
        val avgItemHeight = if (visibleItemsInfo.isNotEmpty()) {
            visibleItemsInfo.sumOf { it.size }.toFloat() / visibleItemsInfo.size
        } else {
            firstVisibleItem.size.toFloat()
        }
        val estimatedTotalHeight = layoutInfo.totalItemsCount * avgItemHeight
        val maxScrollValue = (estimatedTotalHeight - viewportHeight).coerceAtLeast(0f)

        // --- Content Fade Logic ---
        val fadeHeightPx = rememberedContentFadeHeight.toPx()
        if (fadeHeightPx > 0f) {
            // --- Top Fade Calculation ---
            if (rememberedEnableTopFade) {
                val topAlpha = (currentScrollValue / fadeHeightPx).coerceIn(0f, 1f)
                if (topAlpha > 0f) {
                    val topFadeBrush = Brush.verticalGradient(
                        colors = listOf(rememberedContentFadeColor, Color.Transparent),
                        startY = 0f,
                        endY = fadeHeightPx.coerceAtMost(componentHeight)
                    )
                    drawRect(
                        brush = topFadeBrush,
                        alpha = topAlpha,
                        topLeft = Offset.Zero,
                        size = Size(componentWidth, fadeHeightPx.coerceAtMost(componentHeight))
                    )
                }
            }

            // --- Bottom Fade Calculation ---
            if (rememberedEnableBottomFade && maxScrollValue > 0) {
                val distanceToBottom = maxScrollValue - currentScrollValue
                val bottomAlpha = (distanceToBottom / fadeHeightPx).coerceIn(0f, 1f)
                if (bottomAlpha > 0f) {
                    val bottomFadeBrush = Brush.verticalGradient(
                        colors = listOf(Color.Transparent, rememberedContentFadeColor),
                        startY = (componentHeight - fadeHeightPx).coerceAtLeast(0f),
                        endY = componentHeight
                    )
                    drawRect(
                        brush = bottomFadeBrush,
                        alpha = bottomAlpha,
                        topLeft = Offset(0f, (componentHeight - fadeHeightPx).coerceAtLeast(0f)),
                        size = Size(componentWidth, fadeHeightPx.coerceAtMost(componentHeight))
                    )
                }
            }
        }

        // --- Scrollbar Logic ---
        val totalContentHeight = (maxScrollValue + viewportHeight).coerceAtLeast(viewportHeight)
        val scrollValue = currentScrollValue
        val visibleRatio = (viewportHeight / totalContentHeight).coerceIn(0f, 1f)

        if (visibleRatio >= 1f || maxScrollValue <= 0) {
            return@drawWithContent
        }

        val defaultTrackHeight = viewportHeight
        val actualTrackHeight = rememberedTrackHeight?.toPx()?.coerceAtMost(viewportHeight) ?: defaultTrackHeight
        val trackTopOffset = if (actualTrackHeight < viewportHeight) {
            (viewportHeight - actualTrackHeight) / 2f
        } else {
            0f
        }

        val minThumbHeight = rememberedWidth.toPx() * 2
        val maxThumbHeight = actualTrackHeight * rememberedMaxThumbHeightFraction.coerceIn(0f, 1f)
        val computedThumbHeight = visibleRatio * actualTrackHeight
        val scrollBarHeight = computedThumbHeight
            .coerceAtLeast(minThumbHeight)
            .coerceAtMost(maxThumbHeight)
        val availableScrollSpace = maxScrollValue
        val availableTrackSpace = (actualTrackHeight - scrollBarHeight).coerceAtLeast(0f)
        val scrollProgress = if (availableScrollSpace > 0) scrollValue / availableScrollSpace else 0f
        val clampedScrollProgress = scrollProgress.coerceIn(0f, 1f)
        val scrollBarOffsetWithinTrack = clampedScrollProgress * availableTrackSpace
        val scrollBarTopOffset = trackTopOffset + scrollBarOffsetWithinTrack

        val cornerRadius = CornerRadius(rememberedCornerRadius)
        val barWidthPx = rememberedWidth.toPx()
        val paddingPx = rememberedEndPadding

        // Only draw scrollbar if alpha > 0
        if (scrollbarAlpha > 0f) {
            if (rememberedShowTrack) {
                drawRoundRect(
                    color = rememberedTrackColor.copy(alpha = scrollbarAlpha),
                    topLeft = Offset(componentWidth - paddingPx - barWidthPx, trackTopOffset),
                    size = Size(barWidthPx, actualTrackHeight),
                    cornerRadius = cornerRadius
                )
            }

            drawRoundRect(
                color = rememberedScrollBarColor.copy(alpha = scrollbarAlpha),
                topLeft = Offset(componentWidth - paddingPx - barWidthPx, scrollBarTopOffset),
                size = Size(barWidthPx, scrollBarHeight),
                cornerRadius = cornerRadius
            )
        }
    }
}

fun ensureRestSeparatedBySets(components: List<com.gabstra.myworkoutassistant.shared.sets.Set>): List<com.gabstra.myworkoutassistant.shared.sets.Set> {
    val adjustedComponents = mutableListOf<Set>()
    var lastWasSet = false

    for (component in components) {
        if(component !is RestSet) {
            adjustedComponents.add(component)
            lastWasSet = true
        }else{
            if(lastWasSet){
                adjustedComponents.add(component)
            }

            lastWasSet = false
        }
    }
    return adjustedComponents
}

fun ensureRestSeparatedByExercises(components: List<WorkoutComponent>): List<WorkoutComponent> {
    val adjustedComponents = mutableListOf<WorkoutComponent>()
    var lastWasExercise = false

    for (component in components) {
        if (component !is Rest) {
            adjustedComponents.add(component)
            lastWasExercise = true
        } else {
            if (lastWasExercise) {
                //check if the next component if exist is exercise and enabled
                val nextComponentIndex = components.indexOf(component) + 1
                if (nextComponentIndex < components.size) {
                    val nextComponent = components[nextComponentIndex]
                    if (nextComponent.enabled) {
                        adjustedComponents.add(component)
                    } else {
                        adjustedComponents.add(component.copy(enabled = false))
                    }
                }
            }

            lastWasExercise = false
        }
    }
    return adjustedComponents
}

fun dateRangeFor(range: FilterRange): Pair<LocalDate, LocalDate> {
    val today = LocalDate.now()

    return when (range) {
        FilterRange.LAST_WEEK -> {
            val thisMonday = today.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
            val lastMonday = thisMonday.minusWeeks(1)
            val lastSunday = lastMonday.plusDays(6)
            lastMonday to lastSunday
        }
        FilterRange.LAST_7_DAYS -> {
            val start = today.minusDays(6)
            start to today
        }
        FilterRange.LAST_30_DAYS -> {
            val start = today.minusDays(29)
            start to today
        }
        FilterRange.THIS_MONTH -> {
            val ym = YearMonth.now()
            ym.atDay(1) to ym.atEndOfMonth()
        }
        FilterRange.LAST_3_MONTHS -> {
            val start = today.minusMonths(3)
            start to today
        }
        FilterRange.ALL -> LocalDate.MIN to LocalDate.MAX
    }
}

fun List<WorkoutHistory>.filterBy(range: FilterRange): List<WorkoutHistory> {
    val (start, end) = dateRangeFor(range)
    return this.filter { it.date >= start && it.date <= end }
}

@SuppressLint("SuspiciousModifierThen")
@OptIn(ExperimentalComposeUiApi::class)
fun Modifier.repeatActionOnLongPressOrTap(
    coroutineScope: CoroutineScope,
    thresholdMillis: Long = 5000L,
    intervalMillis: Long = 1000L,
    onAction: () -> Unit,
    onTap: () -> Unit
): Modifier = this.then(
    pointerInput(Unit) {
        var repeatedActionHappening = false
        detectTapGestures(
            onPress = { _ ->
                val job = coroutineScope.launch {
                    delay(thresholdMillis)
                    do {
                        repeatedActionHappening = true
                        onAction()
                        delay(intervalMillis)
                    } while (true)
                }
                tryAwaitRelease()
                job.cancel()
                repeatedActionHappening = false
            },
            onTap = {
                if(!repeatedActionHappening) onTap()
            }
        )
    }
)

@SuppressLint("SuspiciousModifierThen")
@OptIn(ExperimentalComposeUiApi::class)
fun Modifier.repeatActionOnLongPress(
    coroutineScope: CoroutineScope,
    thresholdMillis: Long = 5000L,
    intervalMillis: Long = 1000L,
    onPressStart: () -> Unit,
    onBeforeLongPressRepeat: () -> Unit,
    onLongPressRepeat: () -> Unit,
    onRelease: () -> Unit
): Modifier = this.then(
    pointerInput(Unit) {
        detectTapGestures(
            onPress = { _ ->
                onPressStart()
                val job = coroutineScope.launch {
                    delay(thresholdMillis)
                    onBeforeLongPressRepeat()
                    do {
                        delay(intervalMillis)
                        onLongPressRepeat()
                    } while (isActive)
                }

                tryAwaitRelease()
                job.cancel()
                onRelease()
            }
        )
    }
)

suspend fun exportExerciseHistoryToMarkdown(
    context: Context,
    exercise: Exercise,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    exerciseSessionProgressionDao: ExerciseSessionProgressionDao,
    workouts: List<Workout>,
    workoutStore: WorkoutStore
) {
    try {
        when (val result = buildExerciseHistoryMarkdown(
            exercise = exercise,
            workoutHistoryDao = workoutHistoryDao,
            setHistoryDao = setHistoryDao,
            exerciseSessionProgressionDao = exerciseSessionProgressionDao,
            workouts = workouts,
            workoutStore = workoutStore
        )) {
            is ExerciseHistoryMarkdownResult.Success -> {
                val sdf = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.getDefault())
                val timestamp = sdf.format(Date())
                val sanitizedName = exercise.name.replace(Regex("[^a-zA-Z0-9]"), "_").take(50)
                val filename = "exercise_history_${sanitizedName}_$timestamp.md"
                writeMarkdownToDownloadsFolder(context, filename, result.markdown)
            }
            is ExerciseHistoryMarkdownResult.Failure -> {
                withContext(Dispatchers.Main) {
                    Toast.makeText(context, result.message, Toast.LENGTH_SHORT).show()
                }
            }
        }
    } catch (e: Exception) {
        Log.e("ExerciseExport", "Error exporting exercise history", e)
        withContext(Dispatchers.Main) {
            Toast.makeText(context, "Export failed: ${e.message}", Toast.LENGTH_SHORT).show()
        }
    }
}

suspend fun exportWorkoutPlanToMarkdown(
    context: Context,
    workoutStore: WorkoutStore
) {
    try {
        val markdown = buildWorkoutPlanMarkdown(workoutStore)
        val sdf = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.getDefault())
        val timestamp = sdf.format(Date())
        val filename = "workout_plan_export_$timestamp.md"
        writeMarkdownToDownloadsFolder(context, filename, markdown)
    } catch (e: Exception) {
        Log.e("WorkoutPlanExport", "Error exporting workout plan", e)
        withContext(Dispatchers.Main) {
            Toast.makeText(context, "Export failed: ${e.message}", Toast.LENGTH_SHORT).show()
        }
    }
}

suspend fun exportEquipmentToDownloads(
    context: Context,
    workoutStore: WorkoutStore,
    planId: UUID?
): String {
    return withContext(Dispatchers.IO) {
        try {
            val (equipments, accessoryEquipments) = extractEquipmentFromWorkoutPlan(workoutStore, planId)
            val jsonString = equipmentToJSON(equipments, accessoryEquipments)
            
            val sdf = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.getDefault())
            val timestamp = sdf.format(Date())
            
            val planName = if (planId != null) {
                val plan = workoutStore.workoutPlans.find { it.id == planId }
                plan?.name?.replace(Regex("[^a-zA-Z0-9]"), "_") ?: "plan"
            } else {
                "all"
            }
            
            val filename = "equipment_${planName}_$timestamp.json"
            writeJsonToDownloadsFolder(context, filename, jsonString)
            
            filename
        } catch (e: Exception) {
            Log.e("EquipmentExport", "Error exporting equipment", e)
            withContext(Dispatchers.Main) {
                Toast.makeText(context, "Export failed: ${e.message}", Toast.LENGTH_SHORT).show()
            }
            throw e
        }
    }
}

suspend fun backfillExerciseSessionProgressions(
    workoutStore: WorkoutStore,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    exerciseInfoDao: ExerciseInfoDao,
    exerciseSessionProgressionDao: ExerciseSessionProgressionDao,
    db: AppDatabase
) {
    try {
        Log.d("BackfillProgression", "Starting backfill of ExerciseSessionProgressions")
        
        // Get all completed workouts chronologically
        val allWorkouts = workoutHistoryDao.getAllWorkoutHistoriesByIsDone(isDone = true)
            ?: emptyList()
        
        if (allWorkouts.isEmpty()) {
            Log.d("BackfillProgression", "No completed workouts found, skipping backfill")
            return
        }
        
        val sortedWorkouts = allWorkouts.sortedWith(compareBy<WorkoutHistory> { it.date }.thenBy { it.time })
        Log.d("BackfillProgression", "Processing ${sortedWorkouts.size} completed workouts")

        // Build a map of workout ID to Workout for quick lookup
        val workouts = workoutStore.workouts ?: emptyList()
        val workoutMap = workouts.associateBy { it.id }
        
        // Build a map of exercise ID to Exercise for quick lookup
        val exerciseMap = mutableMapOf<UUID, Exercise>()
        workouts.forEach { workout ->
            workout.workoutComponents?.forEach { component ->
                when (component) {
                    is Exercise -> exerciseMap[component.id] = component
                    is Superset -> component.exercises?.forEach { exercise ->
                        exerciseMap[exercise.id] = exercise
                    }
                    is Rest -> Unit
                }
            }
        }

        // Build equipment map
        val equipments = workoutStore.equipments ?: emptyList()
        val equipmentMap = equipments.associateBy { it.id }
        
        // Track ExerciseInfo state as we process workouts chronologically
        // We start with empty state and build it up chronologically to ensure correctness
        val exerciseInfoStateMap = mutableMapOf<UUID, ExerciseInfo>()

        // Process each workout chronologically
        for (workoutHistory in sortedWorkouts) {
            val workout = workoutMap[workoutHistory.workoutId] ?: run {
                Log.d("BackfillProgression", "Workout ${workoutHistory.workoutId} not found in workout store, skipping")
                continue
            }
            
            // Get all exercises from this workout that have enableProgression
            val exercises = mutableListOf<Exercise>()
            workout.workoutComponents?.forEach { component ->
                when (component) {
                    is Exercise -> {
                        if (component.enableProgression && 
                            (component.exerciseType == ExerciseType.WEIGHT || 
                             component.exerciseType == ExerciseType.BODY_WEIGHT)) {
                            exercises.add(component)
                        }
                    }
                    is Superset -> {
                        component.exercises?.forEach { exercise ->
                            if (exercise.enableProgression && 
                                (exercise.exerciseType == ExerciseType.WEIGHT || 
                                 exercise.exerciseType == ExerciseType.BODY_WEIGHT)) {
                                exercises.add(exercise)
                            }
                        }
                    }
                    is Rest -> Unit
                }
            }

            // Get SetHistory entries for this workout
            val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)
                ?.filter { it.exerciseId != null } ?: emptyList()

            // Process each exercise
            for (exercise in exercises) {
                // Check if progression entry already exists
                val existingProgression = exerciseSessionProgressionDao
                    .getByWorkoutHistoryIdAndExerciseId(workoutHistory.id, exercise.id)
                
                if (existingProgression != null) {
                    // Entry already exists, skip
                    Log.d("BackfillProgression", "Progression entry already exists for exercise ${exercise.id} in workout ${workoutHistory.id}, skipping")
                    continue
                }

                // Get SetHistory entries for this exercise in this workout
                val exerciseSetHistories = setHistories
                    .filter { it.exerciseId == exercise.id }
                    .sortedBy { it.order }

                if (exerciseSetHistories.isEmpty()) {
                    // No sets for this exercise in this workout, skip
                    continue
                }

                // Filter out rest sets and rest pause sets
                val currentSession = exerciseSetHistories
                    .dropWhile { it.setData is RestSetData }
                    .dropLastWhile { it.setData is RestSetData }
                    .filter {
                        when (val setData = it.setData) {
                            is BodyWeightSetData -> setData.subCategory != SetSubCategory.RestPauseSet
                            is WeightSetData -> setData.subCategory != SetSubCategory.RestPauseSet
                            is RestSetData -> setData.subCategory != SetSubCategory.RestPauseSet
                            else -> true
                        }
                    }

                if (currentSession.isEmpty()) {
                    continue
                }

                // Convert executed sets to SimpleSet
                val executedSets = currentSession.mapNotNull { setHistory ->
                    when (val setData = setHistory.setData) {
                        is WeightSetData -> {
                            if (setData.subCategory == SetSubCategory.RestPauseSet) null
                            else SimpleSet(setData.getWeight(), setData.actualReps)
                        }
                        is BodyWeightSetData -> {
                            if (setData.subCategory == SetSubCategory.RestPauseSet) null
                            else SimpleSet(setData.getWeight(), setData.actualReps)
                        }
                        else -> null
                    }
                }

                if (executedSets.isEmpty()) {
                    continue
                }

                // Get or reconstruct ExerciseInfo state as it would have been BEFORE this workout
                val exerciseInfoBefore = exerciseInfoStateMap[exercise.id]

                // Calculate expected sets and progression state
                val (expectedSets, progressionState) = calculateExpectedSetsAndProgressionState(
                    exercise = exercise,
                    exerciseInfoBefore = exerciseInfoBefore,
                    workoutStore = workoutStore,
                    equipmentMap = equipmentMap,
                    workoutHistoryDate = workoutHistory.date
                )

                // Handle first sessions (when expectedSets is null because there's no previous session)
                val finalExpectedSets = expectedSets ?: executedSets
                val finalProgressionState = progressionState ?: ProgressionState.PROGRESS
                
                if (finalExpectedSets.isEmpty()) {
                    // No expected sets and no executed sets, skip
                    Log.d("BackfillProgression", "Skipping exercise ${exercise.id} - no sets available")
                    continue
                }

                // Calculate comparisons
                val vsExpected = compareSetListsUnordered(executedSets, finalExpectedSets)
                
                val previousSessionSets = exerciseInfoBefore?.lastSuccessfulSession?.mapNotNull { setHistory ->
                    when (val setData = setHistory.setData) {
                        is WeightSetData -> {
                            if (setData.subCategory == SetSubCategory.RestPauseSet) null
                            else SimpleSet(setData.getWeight(), setData.actualReps)
                        }
                        is BodyWeightSetData -> {
                            if (setData.subCategory == SetSubCategory.RestPauseSet) null
                            else SimpleSet(setData.getWeight(), setData.actualReps)
                        }
                        else -> null
                    }
                } ?: emptyList()

                val vsPrevious = if (previousSessionSets.isNotEmpty()) {
                    compareSetListsUnordered(executedSets, previousSessionSets)
                } else {
                    Ternary.EQUAL
                }

                // Calculate volumes
                val previousSessionVolume = exerciseInfoBefore?.lastSuccessfulSession?.mapNotNull { setHistory ->
                    when (val setData = setHistory.setData) {
                        is WeightSetData -> {
                            if (setData.subCategory == SetSubCategory.RestPauseSet) null
                            else SimpleSet(setData.getWeight(), setData.actualReps)
                        }
                        is BodyWeightSetData -> {
                            if (setData.subCategory == SetSubCategory.RestPauseSet) null
                            else SimpleSet(setData.getWeight(), setData.actualReps)
                        }
                        else -> null
                    }
                }?.sumOf { it.weight * it.reps } ?: 0.0

                val expectedVolume = finalExpectedSets.sumOf { it.weight * it.reps }
                val executedVolume = executedSets.sumOf { it.weight * it.reps }

                // Create and insert ExerciseSessionProgression entry
                val progressionEntry = ExerciseSessionProgression(
                    id = UUID.randomUUID(),
                    workoutHistoryId = workoutHistory.id,
                    exerciseId = exercise.id,
                    expectedSets = finalExpectedSets,
                    progressionState = finalProgressionState,
                    vsExpected = vsExpected,
                    vsPrevious = vsPrevious,
                    previousSessionVolume = previousSessionVolume,
                    expectedVolume = expectedVolume,
                    executedVolume = executedVolume
                )

                exerciseSessionProgressionDao.insert(progressionEntry)
                Log.d("BackfillProgression", "Created progression entry for exercise ${exercise.id} in workout ${workoutHistory.id}")

                // Update ExerciseInfo state for next iteration
                updateExerciseInfoState(
                    exerciseId = exercise.id,
                    currentSession = currentSession,
                    executedSets = executedSets,
                    progressionState = progressionState,
                    vsExpected = vsExpected,
                    exerciseInfoBefore = exerciseInfoBefore,
                    exerciseInfoStateMap = exerciseInfoStateMap,
                    workoutHistoryDate = workoutHistory.date
                )
            }
        }
    } catch (e: Exception) {
        Log.e("BackfillProgression", "Error backfilling ExerciseSessionProgressions", e)
    }
}

private suspend fun calculateExpectedSetsAndProgressionState(
    exercise: Exercise,
    exerciseInfoBefore: ExerciseInfo?,
    workoutStore: WorkoutStore,
    equipmentMap: Map<UUID, WeightLoadedEquipment>,
    workoutHistoryDate: LocalDate?
): Pair<List<SimpleSet>?, ProgressionState?> {
    try {
        // Get available weights
        val availableWeights = when (exercise.exerciseType) {
            ExerciseType.WEIGHT -> {
                exercise.equipmentId?.let { equipmentMap[it]?.getWeightsCombinations() } ?: emptySet()
            }
            ExerciseType.BODY_WEIGHT -> {
                val relativeBodyWeight = workoutStore.weightKg * (exercise.bodyWeightPercentage!! / 100)
                (exercise.equipmentId?.let {
                    equipmentMap[it]?.getWeightsCombinations()?.map { value -> relativeBodyWeight + value }!!.toSet()
                } ?: emptySet()) + setOf(relativeBodyWeight)
            }
            else -> return Pair(null, null)
        }

        if (availableWeights.isEmpty()) {
            return Pair(null, null)
        }

        // Get previous session sets
        val previousSessionSets = exerciseInfoBefore?.lastSuccessfulSession?.mapNotNull { setHistory ->
            when (val setData = setHistory.setData) {
                is WeightSetData -> {
                    if (setData.subCategory == SetSubCategory.RestPauseSet) null
                    else SimpleSet(setData.getWeight(), setData.actualReps)
                }
                is BodyWeightSetData -> {
                    if (setData.subCategory == SetSubCategory.RestPauseSet) null
                    else SimpleSet(setData.getWeight(), setData.actualReps)
                }
                else -> null
            }
        } ?: emptyList()

        if (previousSessionSets.isEmpty()) {
            // No previous session, cannot calculate expected sets
            return Pair(null, null)
        }

        // Compute progression state using the workout history date
        val progressionState = computeProgressionState(exerciseInfoBefore, workoutHistoryDate = workoutHistoryDate)

        // Calculate expected sets based on progression state
        val repsRange = IntRange(exercise.minReps, exercise.maxReps)
        val expectedSets = when (progressionState) {
            ProgressionState.DELOAD -> {
                DoubleProgressionHelper.planDeloadSession(
                    previousSets = previousSessionSets,
                    availableWeights = availableWeights,
                    repsRange = repsRange
                ).sets
            }
            ProgressionState.RETRY -> {
                // For retry, expected sets are the same as previous
                previousSessionSets
            }
            ProgressionState.PROGRESS -> {
                val jumpPolicy = DoubleProgressionHelper.LoadJumpPolicy(
                    defaultPct = exercise.loadJumpDefaultPct ?: 0.025,
                    maxPct = exercise.loadJumpMaxPct ?: 0.5,
                    overcapUntil = exercise.loadJumpOvercapUntil ?: 2
                )
                DoubleProgressionHelper.planNextSession(
                    previousSets = previousSessionSets,
                    availableWeights = availableWeights,
                    repsRange = repsRange,
                    jumpPolicy = jumpPolicy
                ).sets
            }
            ProgressionState.FAILED -> {
                // Should not happen during backfill, but handle it
                previousSessionSets
            }
        }

        return Pair(expectedSets, progressionState)
    } catch (e: Exception) {
        Log.e("BackfillProgression", "Error calculating expected sets", e)
        return Pair(null, null)
    }
}

private fun computeProgressionState(
    exerciseInfo: ExerciseInfo?,
    workoutHistoryDate: LocalDate?
): ProgressionState {
    val fails = exerciseInfo?.sessionFailedCounter?.toInt() ?: 0
    val lastWasDeload = exerciseInfo?.lastSessionWasDeload ?: false

    // For backfill, we use the date from the workout history if available
    val today = workoutHistoryDate ?: LocalDate.now()

    var weeklyCount = 0
    exerciseInfo?.weeklyCompletionUpdateDate?.let { lastUpdate ->
        val startOfThisWeek = today.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
        val startOfLastUpdateWeek = lastUpdate.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
        if (startOfThisWeek.isEqual(startOfLastUpdateWeek)) {
            weeklyCount = exerciseInfo.timesCompletedInAWeek
        }
    }

    val shouldDeload = false // temporarily disable deload: (fails >= 2) && !lastWasDeload
    val shouldRetry = !lastWasDeload && (fails >= 1 || weeklyCount > 1)

    return when {
        shouldDeload -> ProgressionState.DELOAD
        shouldRetry -> ProgressionState.RETRY
        else -> ProgressionState.PROGRESS
    }
}

private suspend fun updateExerciseInfoState(
    exerciseId: UUID,
    currentSession: List<SetHistory>,
    executedSets: List<SimpleSet>,
    progressionState: ProgressionState?,
    vsExpected: Ternary,
    exerciseInfoBefore: ExerciseInfo?,
    exerciseInfoStateMap: MutableMap<UUID, ExerciseInfo>,
    workoutHistoryDate: LocalDate
) {
    try {
        val today = workoutHistoryDate

        // Calculate weekly count
        var weeklyCount = 0
        if (exerciseInfoBefore != null) {
            val lastUpdate = exerciseInfoBefore.weeklyCompletionUpdateDate
            if (lastUpdate != null) {
                val startOfThisWeek = today.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
                val startOfLastUpdateWeek = lastUpdate.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
                if (startOfThisWeek.isEqual(startOfLastUpdateWeek)) {
                    weeklyCount = exerciseInfoBefore.timesCompletedInAWeek
                }
            }
        }
        weeklyCount++

        val isDeloadSession = progressionState == ProgressionState.DELOAD

        val updatedInfo = if (exerciseInfoBefore == null) {
            // First session for this exercise
            ExerciseInfo(
                id = exerciseId,
                bestSession = currentSession,
                lastSuccessfulSession = currentSession,
                successfulSessionCounter = 1u,
                sessionFailedCounter = 0u,
                timesCompletedInAWeek = weeklyCount,
                weeklyCompletionUpdateDate = today,
                lastSessionWasDeload = false
            )
        } else {
            var info = exerciseInfoBefore.copy(version = exerciseInfoBefore.version + 1u)

            if (isDeloadSession) {
                info = info.copy(
                    sessionFailedCounter = 0u,
                    successfulSessionCounter = 0u,
                    lastSessionWasDeload = true
                )
            } else {
                info = info.copy(lastSessionWasDeload = false)

                // Convert best session to SimpleSet list for comparison
                val bestSessionSets = info.bestSession.mapNotNull { setHistory ->
                    when (val setData = setHistory.setData) {
                        is WeightSetData -> {
                            if (setData.subCategory == SetSubCategory.RestPauseSet) return@mapNotNull null
                            SimpleSet(setData.getWeight(), setData.actualReps)
                        }
                        is BodyWeightSetData -> {
                            if (setData.subCategory == SetSubCategory.RestPauseSet) return@mapNotNull null
                            SimpleSet(setData.getWeight(), setData.actualReps)
                        }
                        else -> null
                    }
                }

                // Check if current session is better than best session
                val vsBest = compareSetListsUnordered(executedSets, bestSessionSets)
                if (vsBest == Ternary.ABOVE) {
                    info = info.copy(bestSession = currentSession)
                }

                if (progressionState != null) {
                    if (progressionState == ProgressionState.PROGRESS) {
                        // Success if executed sets are ABOVE or EQUAL to expected sets
                        val isSuccess = vsExpected == Ternary.ABOVE || vsExpected == Ternary.EQUAL

                        info = if (isSuccess) {
                            info.copy(
                                lastSuccessfulSession = currentSession,
                                successfulSessionCounter = info.successfulSessionCounter.inc(),
                                sessionFailedCounter = 0u
                            )
                        } else {
                            info.copy(
                                successfulSessionCounter = 0u,
                                sessionFailedCounter = info.sessionFailedCounter.inc()
                            )
                        }
                    } else {
                        // ProgressionState.RETRY as DELOAD was already handled
                        when (vsExpected) {
                            Ternary.ABOVE -> {
                                // Exceeded retry target - success
                                info = info.copy(
                                    lastSuccessfulSession = currentSession,
                                    successfulSessionCounter = info.successfulSessionCounter.inc(),
                                    sessionFailedCounter = 0u
                                )
                            }
                            Ternary.EQUAL -> {
                                // Met retry target exactly - complete retry, reset counters
                                info = info.copy(
                                    lastSuccessfulSession = currentSession,
                                    successfulSessionCounter = 0u,
                                    sessionFailedCounter = 0u
                                )
                            }
                            Ternary.BELOW, Ternary.MIXED -> {
                                // Below retry target - session failed, don't update counters
                                // Counters remain unchanged (will be incremented elsewhere if needed)
                            }
                        }
                    }
                } else {
                    // No progression state - compare against last successful session
                    val lastSessionSets = info.lastSuccessfulSession.mapNotNull { setHistory ->
                        when (val setData = setHistory.setData) {
                            is WeightSetData -> {
                                if (setData.subCategory == SetSubCategory.RestPauseSet) return@mapNotNull null
                                SimpleSet(setData.getWeight(), setData.actualReps)
                            }
                            is BodyWeightSetData -> {
                                if (setData.subCategory == SetSubCategory.RestPauseSet) return@mapNotNull null
                                SimpleSet(setData.getWeight(), setData.actualReps)
                            }
                            else -> null
                        }
                    }

                    val vsLast = compareSetListsUnordered(executedSets, lastSessionSets)
                    val isSuccess = vsLast == Ternary.ABOVE || vsLast == Ternary.EQUAL

                    info = if (isSuccess) {
                        info.copy(
                            lastSuccessfulSession = currentSession,
                            successfulSessionCounter = info.successfulSessionCounter.inc(),
                            sessionFailedCounter = 0u
                        )
                    } else {
                        info.copy(
                            successfulSessionCounter = 0u,
                            sessionFailedCounter = info.sessionFailedCounter.inc()
                        )
                    }
                }
            }

            info.copy(
                timesCompletedInAWeek = weeklyCount,
                weeklyCompletionUpdateDate = today
            )
        }

        exerciseInfoStateMap[exerciseId] = updatedInfo
    } catch (e: Exception) {
        Log.e("BackfillProgression", "Error updating ExerciseInfo state", e)
    }
}

object Spacing {
    val xs = 6.dp
    val sm = 8.dp
    val md = 12.dp
    val lg = 16.dp
    val xl = 24.dp
}

/**
 * Conflict resolution strategy for merging WorkoutStore data.
 */
enum class ConflictResolution {
    SKIP_DUPLICATES,      // Skip items with duplicate IDs
    GENERATE_NEW_IDS,     // Generate new UUIDs for conflicts
    REPLACE_EXISTING      // Replace existing items with same ID
}

/**
 * Merges an imported WorkoutStore with an existing WorkoutStore.
 * 
 * @param existing The current WorkoutStore in the app
 * @param imported The WorkoutStore to import/merge
 * @param conflictResolution How to handle ID conflicts (default: GENERATE_NEW_IDS)
 * @return Merged WorkoutStore
 */
fun mergeWorkoutStore(
    existing: WorkoutStore,
    imported: WorkoutStore,
    conflictResolution: ConflictResolution = ConflictResolution.SKIP_DUPLICATES
): WorkoutStore {
    // Merge workouts
    val existingWorkoutIds = existing.workouts.map { it.id }.toSet()
    val mergedWorkouts = mutableListOf<Workout>()
    mergedWorkouts.addAll(existing.workouts)
    
    imported.workouts.forEach { importedWorkout ->
        when {
            !existingWorkoutIds.contains(importedWorkout.id) -> {
                // New workout, add it
                mergedWorkouts.add(importedWorkout)
            }
            conflictResolution == ConflictResolution.REPLACE_EXISTING -> {
                // Replace existing workout
                val index = mergedWorkouts.indexOfFirst { it.id == importedWorkout.id }
                if (index >= 0) {
                    mergedWorkouts[index] = importedWorkout
                }
            }
            conflictResolution == ConflictResolution.GENERATE_NEW_IDS -> {
                // Generate new ID for imported workout
                val newId = UUID.randomUUID()
                val newGlobalId = UUID.randomUUID()
                mergedWorkouts.add(
                    importedWorkout.copy(
                        id = newId,
                        globalId = newGlobalId,
                        previousVersionId = null,
                        nextVersionId = null
                    )
                )
            }
            // SKIP_DUPLICATES: do nothing, skip this workout
        }
    }
    
    // Merge equipment
    val existingEquipmentIds = existing.equipments.map { it.id }.toSet()
    val mergedEquipment = mutableListOf<WeightLoadedEquipment>()
    mergedEquipment.addAll(existing.equipments)
    
    imported.equipments.forEach { importedEquipment ->
        when {
            !existingEquipmentIds.contains(importedEquipment.id) -> {
                // New equipment, add it
                mergedEquipment.add(importedEquipment)
            }
            conflictResolution == ConflictResolution.REPLACE_EXISTING -> {
                // Replace existing equipment
                val index = mergedEquipment.indexOfFirst { it.id == importedEquipment.id }
                if (index >= 0) {
                    mergedEquipment[index] = importedEquipment
                }
            }
            conflictResolution == ConflictResolution.GENERATE_NEW_IDS -> {
                // For equipment, skip duplicates when generating new IDs
                // Updating all equipment references in workouts would be complex
                // User can manually add equipment if needed
                // SKIP_DUPLICATES: do nothing, skip this equipment
            }
            // SKIP_DUPLICATES: do nothing, skip this equipment
        }
    }
    
    // Merge accessory equipment
    val existingAccessoryIds = existing.accessoryEquipments.map { it.id }.toSet()
    val mergedAccessories = mutableListOf<AccessoryEquipment>()
    mergedAccessories.addAll(existing.accessoryEquipments)
    
    imported.accessoryEquipments.forEach { importedAccessory ->
        when {
            !existingAccessoryIds.contains(importedAccessory.id) -> {
                // New accessory, add it
                mergedAccessories.add(importedAccessory)
            }
            conflictResolution == ConflictResolution.REPLACE_EXISTING -> {
                // Replace existing accessory
                val index = mergedAccessories.indexOfFirst { it.id == importedAccessory.id }
                if (index >= 0) {
                    mergedAccessories[index] = importedAccessory
                }
            }
            conflictResolution == ConflictResolution.GENERATE_NEW_IDS -> {
                // For accessories, skip duplicates when generating new IDs
                // Updating all accessory references in exercises would be complex
                // User can manually add accessories if needed
                // SKIP_DUPLICATES: do nothing, skip this accessory
            }
            // SKIP_DUPLICATES: do nothing, skip this accessory
        }
    }
    
    // Handle user data: preserve existing values (Option A from plan)
    // Only update if imported values are non-zero/non-default (Option B)
    val mergedBirthDateYear = if (imported.birthDateYear > 0 && imported.birthDateYear != existing.birthDateYear) {
        imported.birthDateYear
    } else {
        existing.birthDateYear
    }
    
    val mergedWeightKg = if (imported.weightKg > 0.0 && imported.weightKg != existing.weightKg) {
        imported.weightKg
    } else {
        existing.weightKg
    }
    
    val mergedProgressionPercentageAmount = if (imported.progressionPercentageAmount > 0.0 && imported.progressionPercentageAmount != existing.progressionPercentageAmount) {
        imported.progressionPercentageAmount
    } else {
        existing.progressionPercentageAmount
    }
    
    // Preserve existing polarDeviceId unless imported has a value
    val mergedPolarDeviceId = imported.polarDeviceId ?: existing.polarDeviceId
    
    // Merge workout plans
    val existingPlanIds = existing.workoutPlans.map { it.id }.toSet()
    val mergedPlans = mutableListOf<WorkoutPlan>()
    mergedPlans.addAll(existing.workoutPlans)
    
    imported.workoutPlans.forEach { importedPlan ->
        when {
            !existingPlanIds.contains(importedPlan.id) -> {
                // New plan, add it
                mergedPlans.add(importedPlan)
            }
            conflictResolution == ConflictResolution.REPLACE_EXISTING -> {
                // Replace existing plan
                val index = mergedPlans.indexOfFirst { it.id == importedPlan.id }
                if (index >= 0) {
                    mergedPlans[index] = importedPlan
                }
            }
            conflictResolution == ConflictResolution.GENERATE_NEW_IDS -> {
                // Generate new ID for imported plan
                val newId = UUID.randomUUID()
                mergedPlans.add(
                    importedPlan.copy(
                        id = newId,
                        workoutIds = importedPlan.workoutIds.map { UUID.randomUUID() } // Also generate new IDs for workouts in plan
                    )
                )
            }
            // SKIP_DUPLICATES: do nothing, skip this plan
        }
    }
    
    return WorkoutStore(
        workouts = mergedWorkouts,
        equipments = mergedEquipment,
        accessoryEquipments = mergedAccessories,
        workoutPlans = mergedPlans,
        birthDateYear = mergedBirthDateYear,
        weightKg = mergedWeightKg,
        progressionPercentageAmount = mergedProgressionPercentageAmount,
        polarDeviceId = mergedPolarDeviceId
    )
}
