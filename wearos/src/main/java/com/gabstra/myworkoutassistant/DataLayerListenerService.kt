package com.gabstra.myworkoutassistant

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.util.Log
import androidx.core.content.edit
import com.gabstra.myworkoutassistant.data.combineChunks
import com.gabstra.myworkoutassistant.data.cancelSyncInProgressNotification
import com.gabstra.myworkoutassistant.data.showSyncCompleteNotification
import com.gabstra.myworkoutassistant.data.showSyncInProgressNotification
import com.gabstra.myworkoutassistant.llm.PhoneLlmOperationResultRegistry
import com.gabstra.myworkoutassistant.scheduling.WorkoutAlarmScheduler
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgressionDao
import com.gabstra.myworkoutassistant.shared.RestHistoryDao
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutRecordDao
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.datalayer.DataLayerPaths
import com.gabstra.myworkoutassistant.shared.datalayer.PROFILE_ID_KEY
import com.gabstra.myworkoutassistant.shared.datalayer.PROFILE_INDEX_JSON_KEY
import com.gabstra.myworkoutassistant.shared.datalayer.PROFILE_NAME_KEY
import com.gabstra.myworkoutassistant.shared.datalayer.SyncHistoryRetention
import com.gabstra.myworkoutassistant.shared.datalayer.SyncPhase
import com.gabstra.myworkoutassistant.shared.datalayer.SyncProgressUpdate
import com.gabstra.myworkoutassistant.shared.datalayer.WorkoutSessionCommand
import com.gabstra.myworkoutassistant.shared.datalayer.WorkoutSessionCommandKeys
import com.gabstra.myworkoutassistant.shared.datalayer.WorkoutSessionCommandType
import com.gabstra.myworkoutassistant.shared.profile.Profiles
import com.gabstra.myworkoutassistant.shared.decompressToString
import com.gabstra.myworkoutassistant.shared.llm.DEFAULT_PHONE_LLM_OPERATION
import com.gabstra.myworkoutassistant.shared.llm.PhoneLlmDataMapKeys
import com.gabstra.myworkoutassistant.shared.llm.PhoneLlmOperationResult
import com.gabstra.myworkoutassistant.shared.fromJSONtoAppBackup
import com.gabstra.myworkoutassistant.shared.motion.ExerciseMovementRef
import com.gabstra.myworkoutassistant.shared.motion.ExerciseMovementStorage
import com.gabstra.myworkoutassistant.shared.motion.restoreExerciseMovementBackups
import com.gabstra.myworkoutassistant.shared.motion.requireExerciseMovementPayloads
import com.gabstra.myworkoutassistant.shared.normalizedWorkoutHistories
import com.gabstra.myworkoutassistant.shared.workout.model.mergeWorkoutRecordsForBackup
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.sync.SyncRequestStartDeadline
import com.gabstra.myworkoutassistant.sync.WearBackupSyncEventPolicy
import com.gabstra.myworkoutassistant.sync.publishProfileBinding
import com.google.android.gms.tasks.Tasks
import com.google.android.gms.wearable.DataEventBuffer
import com.google.android.gms.wearable.DataMap
import com.google.android.gms.wearable.DataMapItem
import com.google.android.gms.wearable.MessageEvent
import com.google.android.gms.wearable.PutDataMapRequest
import com.google.android.gms.wearable.Wearable
import com.google.android.gms.wearable.WearableListenerService
import com.google.android.gms.wearable.NodeClient
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import kotlin.coroutines.EmptyCoroutineContext
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.delay
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.coroutines.withContext
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit
import java.util.UUID
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.ProcessLifecycleOwner
import androidx.room.withTransaction
import kotlin.io.encoding.Base64
import kotlin.io.encoding.ExperimentalEncodingApi

private data class ExerciseMovementInboundTransfer(
    var movementRef: ExerciseMovementRef,
    var expectedChunks: Int,
    val chunks: MutableMap<Int, ByteArray> = mutableMapOf(),
)

class DataLayerListenerService : WearableListenerService() {
    private val dataClient by lazy { Wearable.getDataClient(this) }
    private val nodeClient by lazy { Wearable.getNodeClient(this) }
    @Volatile
    private var localNodeId: String? = null
    // Resolved per use: a profile switch must not leave the service on the old profile's data.
    private val workoutStoreRepository get() = WorkoutStoreRepository.forActiveProfile(this)

    private val appCeh get() = (application as? MyApplication)?.coroutineExceptionHandler ?: EmptyCoroutineContext

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO + appCeh)
    private var backupProcessingJob: Job? = null
    private val syncProgressDispatchLock = Any()
    private var syncProgressDispatchJob: Job? = null
    private data class SyncProgressEchoState(
        var lastEnqueuedPercent: Int = -1,
        var connectedNodeIds: List<String>? = null,
    )
    private val syncProgressEchoStateByTransaction =
        mutableMapOf<String, SyncProgressEchoState>()
    private val pendingSyncPhaseAcks = ConcurrentHashMap<String, CompletableDeferred<Unit>>()
    private data class IncomingBackupProfile(val id: String, val name: String)
    private val incomingBackupProfiles = ConcurrentHashMap<String, IncomingBackupProfile>()
    private val rejectedBackupTransactions = ConcurrentHashMap.newKeySet<String>()

    private val sharedPreferences by lazy {
        getSharedPreferences(
            "backup_state",
            Context.MODE_PRIVATE
        )
    }
    private val gson = Gson()
    private val exerciseMovementTransferLock = Any()
    private val exerciseMovementTransfers = mutableMapOf<String, ExerciseMovementInboundTransfer>()

    private val backupChunkStateLock = Any()
    private var backupChunkStateTransactionId: String? = null
    private var backupChunkStateLoaded = false
    private val receivedBackupChunkIndices = mutableSetOf<Int>()
    private val unscopedBackupChunks = mutableMapOf<Int, ByteArray>()
    @Volatile
    private var legacyBackupChunkMigrationDone = false

    private fun backupChunkKey(transactionId: String, index: Int) =
        "backup_chunk_${transactionId}_$index"

    private fun receivedChunkIndicesKey(transactionId: String) =
        "backup_chunk_indices_$transactionId"

    /**
     * One-time, defensive migration of the legacy combined `backup_chunks` JSON blob.
     * Chunks belonging to a still-active transaction are rewritten under their
     * per-chunk keys; anything else is discarded so old data cannot grow forever.
     */
    @OptIn(ExperimentalEncodingApi::class)
    private fun migrateLegacyBackupChunkStorageIfNeeded() {
        if (legacyBackupChunkMigrationDone) return
        synchronized(backupChunkStateLock) {
            if (legacyBackupChunkMigrationDone) return
            legacyBackupChunkMigrationDone = true
            val legacyJson = sharedPreferences.getString(LEGACY_BACKUP_CHUNKS_KEY, null)
            val activeTransactionId = currentTransactionId
            if (!legacyJson.isNullOrEmpty() && hasStartedSync && activeTransactionId != null) {
                try {
                    val typeToken = object : TypeToken<Map<String, String>>() {}.type
                    val base64Map: Map<String, String> = gson.fromJson(legacyJson, typeToken)
                    val editor = sharedPreferences.edit()
                    val indices = mutableSetOf<Int>()
                    base64Map.forEach { (indexStr, base64String) ->
                        try {
                            val index = indexStr.toInt()
                            editor.putString(
                                backupChunkKey(activeTransactionId, index),
                                Base64.encode(Base64.decode(base64String)),
                            )
                            indices.add(index)
                        } catch (e: Exception) {
                            Log.e(
                                "DataLayerListenerService",
                                "Failed to migrate chunk at index $indexStr: ${e.message}"
                            )
                        }
                    }
                    if (indices.isNotEmpty()) {
                        editor.putStringSet(
                            receivedChunkIndicesKey(activeTransactionId),
                            indices.map { it.toString() }.toSet(),
                        )
                    }
                    editor.apply()
                    Log.d(
                        "DataLayerListenerService",
                        "Migrated ${indices.size} legacy backup chunks for transaction $activeTransactionId"
                    )
                } catch (e: Exception) {
                    Log.e(
                        "DataLayerListenerService",
                        "Failed to migrate legacy backup chunks: ${e.message}",
                        e
                    )
                }
            }
            removeLegacyBackupChunkKeys()
        }
    }

    /** Hydrates the in-memory received-index cache for [transactionId] once per transaction. */
    private fun ensureBackupChunkStateLoaded(transactionId: String?) {
        migrateLegacyBackupChunkStorageIfNeeded()
        synchronized(backupChunkStateLock) {
            if (backupChunkStateLoaded && backupChunkStateTransactionId == transactionId) return
            backupChunkStateTransactionId = transactionId
            backupChunkStateLoaded = true
            receivedBackupChunkIndices.clear()
            unscopedBackupChunks.clear()
            if (transactionId == null) return
            sharedPreferences.getStringSet(receivedChunkIndicesKey(transactionId), null)
                ?.forEach { indexStr ->
                    indexStr.toIntOrNull()?.let(receivedBackupChunkIndices::add)
                }
        }
    }

    /**
     * Drops in-memory and persisted chunk state for the transaction being reset.
     * Persisted keys are deleted so a superseded/failed/expired transaction cannot
     * leave stale chunks behind.
     */
    private fun clearBackupChunkState() {
        val previousTransactionId: String?
        val activeTransactionId = currentTransactionId
        synchronized(backupChunkStateLock) {
            previousTransactionId = backupChunkStateTransactionId
            backupChunkStateTransactionId = null
            backupChunkStateLoaded = true
            receivedBackupChunkIndices.clear()
            unscopedBackupChunks.clear()
        }
        deletePersistedBackupChunks(previousTransactionId)
        if (activeTransactionId != previousTransactionId) {
            deletePersistedBackupChunks(activeTransactionId)
        }
        removeLegacyBackupChunkKeys()
        clearSyncProgressState(previousTransactionId)
        clearSyncProgressState(activeTransactionId)
    }

    /** Starts fresh chunk state for a new transaction, dropping any stale keys for it. */
    private fun resetBackupChunkState(transactionId: String?) {
        val activeTransactionId = currentTransactionId
        val previousTransactionId: String?
        synchronized(backupChunkStateLock) {
            previousTransactionId = backupChunkStateTransactionId
            backupChunkStateTransactionId = transactionId
            backupChunkStateLoaded = true
            receivedBackupChunkIndices.clear()
            unscopedBackupChunks.clear()
        }
        if (previousTransactionId != transactionId) {
            deletePersistedBackupChunks(previousTransactionId)
        }
        if (activeTransactionId != previousTransactionId &&
            activeTransactionId != transactionId
        ) {
            deletePersistedBackupChunks(activeTransactionId)
            clearSyncProgressState(activeTransactionId)
        }
        deletePersistedBackupChunks(transactionId)
        removeLegacyBackupChunkKeys()
        clearSyncProgressState(previousTransactionId)
        clearSyncProgressState(transactionId)
    }

    private fun removeLegacyBackupChunkKeys() {
        sharedPreferences.edit {
            remove(LEGACY_BACKUP_CHUNKS_KEY)
            remove(LEGACY_RECEIVED_CHUNK_INDICES_KEY)
        }
    }

    private fun deletePersistedBackupChunks(transactionId: String?) {
        if (transactionId == null) return
        synchronized(backupChunkStateLock) {
            val indices = mutableSetOf<Int>()
            if (backupChunkStateTransactionId == transactionId) {
                indices.addAll(receivedBackupChunkIndices)
            }
            sharedPreferences.getStringSet(receivedChunkIndicesKey(transactionId), null)
                ?.forEach { indexStr -> indexStr.toIntOrNull()?.let(indices::add) }
            val editor = sharedPreferences.edit()
            editor.remove(receivedChunkIndicesKey(transactionId))
            indices.forEach { index -> editor.remove(backupChunkKey(transactionId, index)) }
            editor.apply()
        }
    }

    /** Persists one chunk under its own key and updates the cached/persisted index set. */
    @OptIn(ExperimentalEncodingApi::class)
    private fun storeReceivedBackupChunk(
        transactionId: String?,
        chunkIndex: Int,
        chunk: ByteArray,
    ) {
        val effectiveTransactionId = transactionId ?: currentTransactionId
        ensureBackupChunkStateLoaded(effectiveTransactionId)
        synchronized(backupChunkStateLock) {
            if (effectiveTransactionId == null) {
                // Invalid/unscoped chunk: keep it in memory only; there is no transaction to recover.
                unscopedBackupChunks[chunkIndex] = chunk
                receivedBackupChunkIndices.add(chunkIndex)
                return
            }
            val indexAdded = receivedBackupChunkIndices.add(chunkIndex)
            sharedPreferences.edit {
                putString(
                    backupChunkKey(effectiveTransactionId, chunkIndex),
                    Base64.encode(chunk),
                )
                if (indexAdded) {
                    putStringSet(
                        receivedChunkIndicesKey(effectiveTransactionId),
                        receivedBackupChunkIndices.map { it.toString() }.toSet(),
                    )
                }
            }
        }
    }

    private fun nextBackupChunkIndex(transactionId: String?): Int {
        val effectiveTransactionId = transactionId ?: currentTransactionId
        ensureBackupChunkStateLoaded(effectiveTransactionId)
        synchronized(backupChunkStateLock) {
            return (receivedBackupChunkIndices.maxOrNull() ?: -1) + 1
        }
    }

    /** Reads each chunk key exactly once for final validation/combination. */
    @OptIn(ExperimentalEncodingApi::class)
    private fun snapshotBackupChunks(transactionId: String?): Map<Int, ByteArray> {
        val effectiveTransactionId = transactionId ?: currentTransactionId
        ensureBackupChunkStateLoaded(effectiveTransactionId)
        synchronized(backupChunkStateLock) {
            if (effectiveTransactionId == null) {
                return unscopedBackupChunks.toMap()
            }
            val snapshot = mutableMapOf<Int, ByteArray>()
            receivedBackupChunkIndices.forEach { index ->
                val encoded = sharedPreferences.getString(
                    backupChunkKey(effectiveTransactionId, index),
                    null,
                )
                if (encoded == null) {
                    Log.e(
                        "DataLayerListenerService",
                        "Missing persisted backup chunk $index for transaction $effectiveTransactionId"
                    )
                    return@forEach
                }
                runCatching { Base64.decode(encoded) }
                    .onSuccess { snapshot[index] = it }
                    .onFailure { e ->
                        Log.e(
                            "DataLayerListenerService",
                            "Failed to decode chunk $index for transaction $effectiveTransactionId: ${e.message}",
                            e
                        )
                    }
            }
            return snapshot
        }
    }

    private fun snapshotReceivedBackupChunkIndices(transactionId: String?): Set<Int> {
        val effectiveTransactionId = transactionId ?: currentTransactionId
        ensureBackupChunkStateLoaded(effectiveTransactionId)
        synchronized(backupChunkStateLock) {
            return receivedBackupChunkIndices.toSet()
        }
    }

    private fun receivedBackupChunkCount(transactionId: String?): Int {
        val effectiveTransactionId = transactionId ?: currentTransactionId
        ensureBackupChunkStateLoaded(effectiveTransactionId)
        synchronized(backupChunkStateLock) {
            return receivedBackupChunkIndices.size
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

    private val completedTransactionIdsLock = Any()
    private var completedTransactionIdsCache: LinkedHashSet<String>? = null

    private fun loadCompletedTransactionIds(): MutableList<String> {
        val json = sharedPreferences.getString(PREFS_COMPLETED_ORDERED, null)
        if (!json.isNullOrEmpty()) {
            return try {
                val typeToken = object : TypeToken<MutableList<String>>() {}.type
                gson.fromJson<MutableList<String>>(json, typeToken) ?: mutableListOf()
            } catch (e: Exception) {
                Log.e("DataLayerListenerService", "Failed to parse completedTransactionIds list", e)
                mutableListOf()
            }
        }
        val legacy = sharedPreferences.getStringSet("completedTransactionIds", emptySet()) ?: emptySet()
        return legacy.toList().takeLast(MAX_COMPLETED_TRANSACTION_IDS).toMutableList()
    }

    /** Caller must hold [completedTransactionIdsLock]. */
    private fun completedTransactionIds(): LinkedHashSet<String> {
        completedTransactionIdsCache?.let { return it }
        return LinkedHashSet(loadCompletedTransactionIds()).also {
            completedTransactionIdsCache = it
        }
    }

    private fun saveCompletedTransactionIds(ids: Collection<String>) {
        val trimmed =
            if (ids.size > MAX_COMPLETED_TRANSACTION_IDS) {
                ids.toList().takeLast(MAX_COMPLETED_TRANSACTION_IDS)
            } else {
                ids.toList()
            }
        sharedPreferences.edit {
            putString(PREFS_COMPLETED_ORDERED, gson.toJson(trimmed))
            remove("completedTransactionIds")
        }
    }

    private fun completedTransactionIdsContains(transactionId: String): Boolean =
        synchronized(completedTransactionIdsLock) {
            transactionId in completedTransactionIds()
        }

    private lateinit var context: WearableListenerService

    override fun onCreate() {
        super.onCreate()
        // Deadlines scheduled by a previous instance must reach this one: a re-bind replaces
        // the instance while its pending timeout can still be in the queue.
        activeService = this
        // Foreground before any onDataChanged: otherwise GMS can tear down the service before
        // SYNC_REQUEST / chunks are delivered (see WearableService "disconnected before delivering").
        DataLayerSyncForegroundHelper.startFromServiceCreated(this)
        context = this
        scope.launch {
            resolveLocalNodeIdInBackground()
        }

        // Detect service restart and handle incomplete syncs. A re-bind within the
        // same process is not a restart: the sync state is not stale and transfer
        // or processing may be mid-flight, so auto-heal must not fire.
        if (serviceCreatedInThisProcess) {
            Log.d(
                "DataLayerSync",
                "Service re-bound within the same process; skipping restart auto-heal."
            )
        } else {
            serviceCreatedInThisProcess = true
            detectAndHandleServiceRestart()
        }
        reconcileBackupSyncStateIfNeeded()
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

        if (hasIncompleteSync && currentTransactionId == activeProcessingTransactionId) {
            // The service was re-bound while backup processing from this process is
            // still running; the persisted state only looks stale. Do not heal.
            Log.i(
                "DataLayerSync",
                "Service re-bound during active sync; processing still running for transaction: $currentTransactionId. Skipping auto-heal."
            )
        } else if (hasIncompleteSync && (currentTime - lastServiceStartTime > serviceRestartThreshold)) {
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
                    val receivedIndices = snapshotReceivedBackupChunkIndices(transactionId)
                    val missingIndices = (0 until expectedChunks).filter { it !in receivedIndices }
                    
                    if (missingIndices.isEmpty() && receivedIndices.size == expectedChunks) {
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
                        sendMissingChunksError(
                            transactionId ?: return@launch,
                            missingIndices,
                            expectedChunks,
                            receivedIndices.size,
                        )
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
        sharedPreferences.edit {
            putLong("last_service_start_time", currentTime)
        }
    }
    
    /**
     * Cleans up incomplete sync state and notifies UI.
     * This clears sync state when sync fails or times out.
     */
    private fun cleanupIncompleteSyncState() {
        syncRequestStartDeadline.cancel()
        backupProcessingJob?.cancel()
        backupProcessingJob = null
        removeTimeout()
        removeRetryTimeout()
        clearSyncInProgressNotification()
        clearBackupChunkState()
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

    private fun cancelBackupTransaction(transactionId: String) {
        val pendingRequestCancellation = syncRequestStartDeadline.cancel(transactionId)
        val activeTransactionId = currentTransactionId
        if (activeTransactionId != null && activeTransactionId != transactionId) {
            Log.d(
                "DataLayerSync",
                "Ignoring cancellation for inactive transaction: $transactionId"
            )
            return
        }
        if (activeTransactionId == null) {
            when (pendingRequestCancellation) {
                is SyncRequestStartDeadline.Cancellation.Cancelled -> {
                    incomingBackupProfiles.remove(transactionId)
                    rememberRejectedBackupTransaction(transactionId)
                    sendBackupFailedBroadcast()
                    DataLayerSyncForegroundHelper.startFromServiceCreated(this)
                    Log.d(
                        "DataLayerSync",
                        "Cancelled pending sync request before backup start: $transactionId",
                    )
                    return
                }
                is SyncRequestStartDeadline.Cancellation.DifferentPendingRequest -> {
                    Log.d(
                        "DataLayerSync",
                        "Ignoring cancellation for stale sync request: $transactionId; pending=${pendingRequestCancellation.transactionId}",
                    )
                    return
                }
                SyncRequestStartDeadline.Cancellation.None -> Unit
            }
        }
        incomingBackupProfiles.remove(transactionId)
        rememberRejectedBackupTransaction(transactionId)
        cleanupIncompleteSyncState()
        DataLayerSyncForegroundHelper.startFromServiceCreated(this)
        Log.d("DataLayerSync", "Cancelled app backup transaction: $transactionId")
    }

    private fun sendBackupFailedBroadcast() {
        clearSyncInProgressNotification()
        sendBroadcast(Intent(INTENT_ID).apply {
            putExtra(APP_BACKUP_FAILED, APP_BACKUP_FAILED)
            setPackage(packageName)
        })
    }

    override fun onMessageReceived(messageEvent: MessageEvent) {
        val path = messageEvent.path
        if (DataLayerPaths.matchesPrefix(path, DataLayerPaths.SYNC_CANCEL_PREFIX)) {
            val transactionId = DataLayerPaths.parseTransactionId(
                path,
                DataLayerPaths.SYNC_CANCEL_PREFIX
            ) ?: messageEvent.data.toString(Charsets.UTF_8).takeIf { it.isNotBlank() }
            transactionId?.let(::cancelBackupTransaction)
            return
        }

        if (DataLayerPaths.matchesPrefix(path, DataLayerPaths.SYNC_PHASE_ACK_PREFIX)) {
            val transactionId = DataLayerPaths.parseTransactionId(
                path,
                DataLayerPaths.SYNC_PHASE_ACK_PREFIX
            ) ?: return
            val phase = SyncPhase.fromWireValue(messageEvent.data.toString(Charsets.UTF_8)) ?: return
            pendingSyncPhaseAcks.remove(syncPhaseAckKey(transactionId, phase))?.complete(Unit)
        }
    }

    private suspend fun publishSyncPhaseAndWaitForPhone(
        transactionId: String,
        phase: SyncPhase,
        publish: suspend () -> Unit,
    ) {
        val key = syncPhaseAckKey(transactionId, phase)
        val acknowledgment = CompletableDeferred<Unit>()
        pendingSyncPhaseAcks.put(key, acknowledgment)?.cancel()
        try {
            publish()
            val acknowledged = withTimeoutOrNull(SYNC_PHASE_ACK_TIMEOUT_MS) {
                acknowledgment.await()
                true
            } ?: false
            if (!acknowledged) {
                Log.w(
                    "DataLayerSync",
                    "Phone did not acknowledge displayed phase=$phase transaction=$transactionId"
                )
            }
        } finally {
            pendingSyncPhaseAcks.remove(key, acknowledgment)
        }
    }

    private fun syncPhaseAckKey(transactionId: String, phase: SyncPhase) =
        "$transactionId:${phase.name}"

    /**
     * If persisted prefs are mutually inconsistent (e.g. process death mid-write), reset to a clean state.
     */
    private fun reconcileBackupSyncStateIfNeeded() {
        val inconsistent =
            (hasStartedSync && currentTransactionId == null) ||
                (!hasStartedSync && currentTransactionId != null && expectedChunks > 0)
        if (inconsistent) {
            Log.w(
                "DataLayerSync",
                "Reconciling inconsistent backup sync prefs (hasStartedSync=$hasStartedSync, currentTransactionId=$currentTransactionId, expectedChunks=$expectedChunks)"
            )
            cleanupIncompleteSyncState()
        }
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

    /**
     * A running sync must be visible when the app is not in front of the athlete: the
     * foreground-service notification is IMPORTANCE_LOW and never surfaces on Wear.
     */
    private fun notifySyncStarted() {
        if (ProcessLifecycleOwner.get().lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) {
            return
        }
        showSyncInProgressNotification(this)
    }

    private fun clearSyncInProgressNotification() {
        cancelSyncInProgressNotification(this)
    }

    private val handler = syncHandler
    private val syncRequestStartDeadline = SyncRequestStartDeadline(
        handler = handler,
        timeoutMillis = SYNC_REQUEST_START_TIMEOUT_MS,
    ) { transactionId ->
        if (!hasStartedSync && currentTransactionId == null) {
            Log.w("DataLayerSync", "SYNC_REQUEST expired before backup start: $transactionId")
            incomingBackupProfiles.remove(transactionId)
            rememberRejectedBackupTransaction(transactionId)
            sendBackupFailedBroadcast()
            DataLayerSyncForegroundHelper.startFromServiceCreated(this@DataLayerListenerService)
            scope.launch {
                sendSyncErrorForRecovery(
                    transactionId,
                    "SYNC_START_TIMEOUT: backup start was not received",
                )
            }
        }
    }

    /**
     * Runs on the process-wide timeout scheduler. Late retry chunks can re-arm this timeout
     * after the sync already completed and cleaned up; without an active sync there is nothing
     * to fail and the success screen must not be overwritten.
     */
    private fun handleCompletionTimeout() {
        if (!hasStartedSync || currentTransactionId == null) {
            Log.d(
                "DataLayerListenerService",
                "Timeout triggered after sync end; ignoring (no active sync)"
            )
            return
        }
        Log.d("DataLayerListenerService", "Timeout triggered")

        clearSyncInProgressNotification()
        val intent = Intent(INTENT_ID).apply {
            putExtra(APP_BACKUP_FAILED, APP_BACKUP_FAILED)
            setPackage(packageName)
        }
        sendBroadcast(intent)

        removeRetryTimeout()
        clearBackupChunkState()
        expectedChunks = 0
        hasStartedSync = false
        currentTransactionId = null
        ignoreUntilStartOrEnd = true
    }

    private fun handleRetryTimeout() {
        Log.w("DataLayerSync", "Retry timeout triggered - aborting stuck backup sync")
        cleanupIncompleteSyncState()
    }

    private fun postTimeout(chunksCount: Int = expectedChunks) {
        // Use dynamic timeout calculation based on chunk count
        val timeoutMs = if (chunksCount > 0) {
            calculateCompletionTimeout(chunksCount)
        } else {
            // Fallback to default if chunksCount not available yet
            BASE_COMPLETION_TIMEOUT_MS + PER_CHUNK_TIMEOUT_MS
        }
        Log.d("DataLayerSync", "Posting timeout: ${timeoutMs}ms for $chunksCount chunks")
        syncHandler.postDelayed(completionTimeoutRunnable, timeoutMs)
    }

    /**
     * Receiving is done; the only remaining work is local. The transfer budget above only models
     * chunk delivery, so it must be replaced by a deadline sized to the payload being parsed.
     */
    private fun postProcessingTimeout(jsonChars: Int) {
        val timeoutMs = minOf(
            PROCESSING_BASE_TIMEOUT_MS + PROCESSING_TIMEOUT_PER_MEGACHAR_MS * (jsonChars / 1_000_000),
            MAX_COMPLETION_TIMEOUT_MS,
        )
        Log.d("DataLayerSync", "Posting processing timeout: ${timeoutMs}ms for $jsonChars chars")
        syncHandler.postDelayed(completionTimeoutRunnable, timeoutMs)
    }

    private fun postRetryTimeout(chunksCount: Int = expectedChunks) {
        val baseTimeout = if (chunksCount > 0) {
            calculateCompletionTimeout(chunksCount)
        } else {
            BASE_COMPLETION_TIMEOUT_MS
        }
        val retryTimeoutMs = minOf(baseTimeout * 2, MAX_COMPLETION_TIMEOUT_MS)
        Log.d("DataLayerSync", "Posting retry timeout: ${retryTimeoutMs}ms for $chunksCount chunks")
        syncHandler.postDelayed(retryTimeoutRunnable, retryTimeoutMs)
    }

    private fun removeTimeout() {
        syncHandler.removeCallbacks(completionTimeoutRunnable)
    }

    private fun removeRetryTimeout() {
        syncHandler.removeCallbacks(retryTimeoutRunnable)
    }

    private fun markTransactionCompleted(transactionId: String?) {
        if (transactionId.isNullOrBlank()) return
        incomingBackupProfiles.remove(transactionId)
        rejectedBackupTransactions.remove(transactionId)
        synchronized(completedTransactionIdsLock) {
            val updated = completedTransactionIds()
            val changed = updated.add(transactionId)
            var trimmed = false
            while (updated.size > MAX_COMPLETED_TRANSACTION_IDS) {
                updated.remove(updated.first())
                trimmed = true
            }
            if (changed || trimmed) {
                saveCompletedTransactionIds(updated)
            }
        }
    }

    private fun rememberRejectedBackupTransaction(transactionId: String) {
        rejectedBackupTransactions.add(transactionId)
        while (rejectedBackupTransactions.size > MAX_COMPLETED_TRANSACTION_IDS) {
            rejectedBackupTransactions.iterator().let { iterator ->
                if (iterator.hasNext()) rejectedBackupTransactions.remove(iterator.next())
            }
        }
    }

    /** Resolve and pin the named backup target, without changing this watch's active selection. */
    private fun pinIncomingBackupProfile(transactionId: String?, dataMap: DataMap): Boolean {
        if (transactionId.isNullOrBlank()) return true
        if (transactionId in rejectedBackupTransactions) return false

        dataMap.getString(PROFILE_INDEX_JSON_KEY)?.let { remoteIndexJson ->
            if (!Profiles.applyRemoteIndexJson(this, remoteIndexJson)) {
                rejectIncomingBackupProfile(transactionId, "Phone profile index is invalid")
                return false
            }
        }

        val requestedId = dataMap.getString(PROFILE_ID_KEY)
        val requestedName = dataMap.getString(PROFILE_NAME_KEY)
        val existing = incomingBackupProfiles[transactionId]
        if (existing != null) {
            if ((requestedId != null && requestedId != existing.id) ||
                (requestedName != null && requestedName.trim() != existing.name)
            ) {
                rejectIncomingBackupProfile(transactionId, "Backup profile metadata changed during transfer")
                return false
            }
            return true
        }

        val profileId = Profiles.ensureIncomingBackupProfile(this, requestedId, requestedName)
        if (profileId == null) {
            rejectIncomingBackupProfile(
                transactionId,
                "Backup names an unknown profile without a valid profile name/id",
            )
            return false
        }
        val profileName = Profiles.profiles(this).firstOrNull { it.id == profileId }?.name
        if (profileName.isNullOrBlank()) {
            rejectIncomingBackupProfile(transactionId, "Backup target profile could not be resolved")
            return false
        }
        incomingBackupProfiles.putIfAbsent(transactionId, IncomingBackupProfile(profileId, profileName))
        return true
    }

    private fun rejectIncomingBackupProfile(transactionId: String, reason: String) {
        if (transactionId in rejectedBackupTransactions) return
        rememberRejectedBackupTransaction(transactionId)
        incomingBackupProfiles.remove(transactionId)
        Log.e("DataLayerSync", "Rejecting backup transaction $transactionId: $reason")
        scope.launch(Dispatchers.IO) {
            runCatching { sendSyncErrorForRecovery(transactionId, "INVALID_PROFILE: $reason") }
        }
    }

    private fun shouldIgnoreBackupEvent(
        transactionId: String?,
        timestampStr: String?,
        isRetry: Boolean,
        eventType: String,
        ignoreUntilStartOrEnd: Boolean
    ): Boolean {
        val staleThresholdMs = getSharedPreferences("sync_timeouts", Context.MODE_PRIVATE)
            .getLong("stale_backup_event_threshold_ms", 300000L)
        val nowMs = System.currentTimeMillis()
        val ignore = WearBackupSyncEventPolicy.shouldIgnoreBackupEvent(
            isTransactionCompleted = { completedTransactionIdsContains(it) },
            transactionId = transactionId,
            timestampStr = timestampStr,
            isRetry = isRetry,
            eventType = eventType,
            ignoreUntilStartOrEnd = ignoreUntilStartOrEnd,
            nowMs = nowMs,
            staleThresholdMs = staleThresholdMs
        )
        if (!ignore && ignoreUntilStartOrEnd && eventType == "app_backup_start") {
            val ts = timestampStr?.toLongOrNull()
            if (ts != null && nowMs - ts > staleThresholdMs) {
                Log.d(
                    "DataLayerSync",
                    "Stale-age exempt for app_backup_start while gated (recovery), tx=$transactionId"
                )
            }
        }
        return ignore
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

    /**
     * Resolves the local node on a background scope, retrying a few times so the
     * main-thread fallback in [isSelfOriginatedEvent] stays genuinely rare.
     */
    private suspend fun resolveLocalNodeIdInBackground() {
        repeat(LOCAL_NODE_RESOLUTION_ATTEMPTS) { attempt ->
            val resolved = runCatching {
                Tasks.await(
                    nodeClient.localNode,
                    LOCAL_NODE_RESOLUTION_TIMEOUT_MS,
                    TimeUnit.MILLISECONDS,
                ).id
            }.getOrNull()
            if (resolved != null) {
                localNodeId = resolved
                return
            }
            if (attempt < LOCAL_NODE_RESOLUTION_ATTEMPTS - 1) {
                delay(LOCAL_NODE_RESOLUTION_RETRY_DELAY_MS)
            }
        }
        Log.w(
            "DataLayerSync",
            "Could not resolve local node id in background; self-event detection will use the fallback await"
        )
    }

    private fun resolveLocalNodeId(): String? {
        localNodeId?.let { return it }
        return runCatching {
            // Bounded so a stuck GMS task cannot block the caller indefinitely.
            Tasks.await(
                nodeClient.localNode,
                LOCAL_NODE_RESOLUTION_TIMEOUT_MS,
                TimeUnit.MILLISECONDS,
            ).id
        }.getOrNull()?.also { resolved ->
            localNodeId = resolved
        }
    }

    private fun isSelfOriginatedEvent(uri: Uri): Boolean {
        val sourceNodeId = uri.host ?: return false
        val ownNodeId = resolveLocalNodeId() ?: return false
        return sourceNodeId == ownNodeId
    }

    private fun handlePhoneLlmOperationResult(
        path: String,
        dataMap: com.google.android.gms.wearable.DataMap,
    ) {
        val requestId = DataLayerPaths.parseTransactionId(
            path,
            DataLayerPaths.PHONE_LLM_OPERATION_RESULT_PREFIX
        ) ?: dataMap.getString(PhoneLlmDataMapKeys.REQUEST_ID)

        if (requestId.isNullOrBlank()) {
            Log.w("PhoneLlmOperation", "Received LLM operation result without requestId")
            return
        }

        val resultJson = dataMap.getString(PhoneLlmDataMapKeys.RESULT_JSON)
        val result = if (resultJson.isNullOrBlank()) {
            PhoneLlmOperationResult.error(
                requestId = requestId,
                operation = DEFAULT_PHONE_LLM_OPERATION,
                errorMessage = "Missing LLM operation result payload."
            )
        } else {
            runCatching {
                val parsedResult = gson.fromJson(
                    resultJson,
                    PhoneLlmOperationResult::class.java
                ) ?: error("Invalid LLM operation result payload.")
                parsedResult.copy(requestId = requestId)
            }.getOrElse { exception ->
                PhoneLlmOperationResult.error(
                    requestId = requestId,
                    operation = DEFAULT_PHONE_LLM_OPERATION,
                    errorMessage = exception.message ?: "Failed to parse LLM operation result."
                )
            }
        }

        PhoneLlmOperationResultRegistry.completeResult(requestId, result)
        Log.d(
            "PhoneLlmOperation",
            "Received LLM operation result for request: $requestId, status: ${result.status}"
        )
    }

    private fun handleExerciseMovementDataItem(path: String, dataMap: DataMap) {
        val isStartPath = DataLayerPaths.matchesPrefix(path, DataLayerPaths.EXERCISE_MOVEMENT_START_PREFIX)
        val isChunkPath = DataLayerPaths.matchesPrefix(path, DataLayerPaths.EXERCISE_MOVEMENT_CHUNK_PREFIX)
        val transactionId = if (isStartPath) {
            DataLayerPaths.parseTransactionId(path, DataLayerPaths.EXERCISE_MOVEMENT_START_PREFIX)
        } else {
            DataLayerPaths.parseTransactionId(path, DataLayerPaths.EXERCISE_MOVEMENT_CHUNK_PREFIX)
        } ?: dataMap.getString("transactionId")

        if (transactionId == null) {
            Log.w("DataLayerSync", "Received exercise movement data without transactionId")
            return
        }

        val movementRef = readExerciseMovementRef(dataMap)
        if (movementRef == null) {
            scope.launch {
                sendExerciseMovementSyncError(transactionId, "Invalid exercise movement metadata")
            }
            return
        }

        val expectedChunks = if (dataMap.containsKey("chunksCount")) {
            dataMap.getInt("chunksCount")
        } else {
            0
        }
        val chunkIndex = if (isChunkPath) {
            DataLayerPaths.parseChunkIndex(path, DataLayerPaths.EXERCISE_MOVEMENT_CHUNK_PREFIX)
                ?: if (dataMap.containsKey("chunkIndex")) dataMap.getInt("chunkIndex") else -1
        } else {
            -1
        }
        val chunk = dataMap.getByteArray("chunk")

        val completedTransfer = synchronized(exerciseMovementTransferLock) {
            val transfer = exerciseMovementTransfers.getOrPut(transactionId) {
                ExerciseMovementInboundTransfer(
                    movementRef = movementRef,
                    expectedChunks = expectedChunks,
                )
            }
            transfer.movementRef = movementRef
            if (expectedChunks > 0) {
                transfer.expectedChunks = expectedChunks
            }
            if (chunk != null && chunkIndex >= 0) {
                transfer.chunks[chunkIndex] = chunk
            }

            if (transfer.expectedChunks > 0 && transfer.chunks.size >= transfer.expectedChunks) {
                exerciseMovementTransfers.remove(transactionId)
                ExerciseMovementInboundTransfer(
                    movementRef = transfer.movementRef,
                    expectedChunks = transfer.expectedChunks,
                    chunks = transfer.chunks.toMutableMap(),
                )
            } else {
                null
            }
        }

        if (completedTransfer != null) {
            scope.launch(Dispatchers.IO) {
                processCompletedExerciseMovementTransfer(transactionId, completedTransfer)
            }
        }
    }

    private fun readExerciseMovementRef(dataMap: DataMap): ExerciseMovementRef? {
        val movementId = dataMap.getString("movementId")?.takeIf { it.isNotBlank() } ?: return null
        val contentHash = dataMap.getString("contentHash")?.takeIf { it.isNotBlank() } ?: return null
        val format = dataMap.getString("format") ?: ExerciseMovementRef.FORMAT_WEAR_SKELETON_JSON
        val version = if (dataMap.containsKey("version")) dataMap.getInt("version") else 1
        return ExerciseMovementRef(
            movementId = movementId,
            contentHash = contentHash,
            format = format,
            version = version,
        )
    }

    private suspend fun processCompletedExerciseMovementTransfer(
        transactionId: String,
        transfer: ExerciseMovementInboundTransfer,
    ) {
        try {
            val sortedChunks = (0 until transfer.expectedChunks).mapNotNull { index ->
                transfer.chunks[index]
            }
            if (sortedChunks.size != transfer.expectedChunks) {
                sendExerciseMovementSyncError(
                    transactionId,
                    "Missing exercise movement chunks: expected ${transfer.expectedChunks}, received ${sortedChunks.size}"
                )
                return
            }

            val compressedMovementJson = combineChunks(sortedChunks)
            val movementJson = decompressToString(compressedMovementJson)
            ExerciseMovementStorage.writeMovementJson(
                context = this@DataLayerListenerService,
                movementRef = transfer.movementRef,
                json = movementJson,
            )

            Log.d(
                "DataLayerSync",
                "Stored exercise movement ${transfer.movementRef.movementId} for transaction: $transactionId"
            )
            sendExerciseMovementSyncComplete(transactionId)
        } catch (exception: Exception) {
            Log.e("DataLayerSync", "Failed to process exercise movement transaction: $transactionId", exception)
            sendExerciseMovementSyncError(
                transactionId,
                exception.message ?: "Unknown error processing exercise movement"
            )
        }
    }

    private suspend fun sendExerciseMovementSyncComplete(transactionId: String) {
        val completePath = DataLayerPaths.buildPath(DataLayerPaths.SYNC_COMPLETE_PREFIX, transactionId)
        val completeDataMapRequest = PutDataMapRequest.create(completePath)
        completeDataMapRequest.dataMap.putString("transactionId", transactionId)
        completeDataMapRequest.dataMap.putString("timestamp", System.currentTimeMillis().toString())
        val completeRequest = completeDataMapRequest.asPutDataRequest().setUrgent()
        Tasks.await(dataClient.putDataItem(completeRequest))
    }

    private suspend fun sendExerciseMovementSyncError(transactionId: String, errorMessage: String) {
        val errorPath = DataLayerPaths.buildPath(DataLayerPaths.SYNC_ERROR_PREFIX, transactionId)
        val errorDataMapRequest = PutDataMapRequest.create(errorPath)
        errorDataMapRequest.dataMap.putString("transactionId", transactionId)
        errorDataMapRequest.dataMap.putString("errorMessage", errorMessage)
        errorDataMapRequest.dataMap.putString("timestamp", System.currentTimeMillis().toString())
        val errorRequest = errorDataMapRequest.asPutDataRequest().setUrgent()
        Tasks.await(dataClient.putDataItem(errorRequest))
    }

    private fun parseWorkoutSessionCommand(dataMap: DataMap): WorkoutSessionCommand? {
        val type = WorkoutSessionCommandType.fromWireValue(
            dataMap.getString(WorkoutSessionCommandKeys.COMMAND)
        ) ?: return null
        val workoutId = dataMap.getString(WorkoutSessionCommandKeys.WORKOUT_ID)
            ?.let { runCatching { UUID.fromString(it) }.getOrNull() }
        val sentAtEpochMs = dataMap.getLong(WorkoutSessionCommandKeys.SENT_AT_EPOCH_MS, -1L)
        if (sentAtEpochMs <= 0L) return null
        return WorkoutSessionCommand(
            type = type,
            workoutId = workoutId,
            enabled = dataMap.getBoolean(WorkoutSessionCommandKeys.ENABLED, false),
            sentAtEpochMs = sentAtEpochMs,
        )
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
                if (isSelfOriginatedEvent(uri)) {
                    Log.d("DataLayerSync", "Ignoring self-originated data event: ${uri.path}")
                    return@forEach
                }

                val path = uri.path ?: return@forEach
                when {
                    path == DataLayerPaths.WORKOUT_SESSION_COMMAND_PATH -> {
                        val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                        // A command for another profile's session is not ours to apply.
                        val commandProfileId = dataMap.getString(PROFILE_ID_KEY)
                        val commandIsForThisWatch = commandProfileId == null ||
                            commandProfileId == Profiles.activeProfileId(this@DataLayerListenerService)
                        val command = if (commandIsForThisWatch) {
                            parseWorkoutSessionCommand(dataMap)
                        } else {
                            null
                        }
                        if (command != null) {
                            Log.d(
                                "WorkoutSessionCommand",
                                "Received ${command.type} workoutId=${command.workoutId} " +
                                    "enabled=${command.enabled}"
                            )
                            com.gabstra.myworkoutassistant.data.WorkoutSessionCommandBus.publish(command)
                        }
                        // Consume the item so a reconnect cannot replay an old toggle.
                        scope.launch(Dispatchers.IO) {
                            runCatching { dataClient.deleteDataItems(uri) }
                        }
                    }

                    DataLayerPaths.matchesPrefix(
                        path,
                        DataLayerPaths.PHONE_LLM_OPERATION_RESULT_PREFIX
                    ) -> {
                        val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                        // JSON parse can be large; keep it off the listener callback thread.
                        scope.launch(Dispatchers.IO) {
                            handlePhoneLlmOperationResult(path, dataMap)
                        }
                    }

                    DataLayerPaths.matchesPrefix(path, DataLayerPaths.SYNC_ACK_PREFIX) -> {
                        val transactionId =
                            DataLayerPaths.parseTransactionId(path, DataLayerPaths.SYNC_ACK_PREFIX)

                        // Ignore ACKs without transactionId
                        transactionId?.let { tid ->
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
                // Ignore DataItem deletions here as well. Deletion events (e.g., after phone uninstall
                // or sender-side cleanup) must not be interpreted as new backup/sync starts.
                if (dataEvent.type != com.google.android.gms.wearable.DataEvent.TYPE_CHANGED) {
                    return@forEach
                }

                val uri = dataEvent.dataItem.uri
                if (isSelfOriginatedEvent(uri)) {
                    Log.d("DataLayerSync", "Ignoring self-originated data event: ${uri.path}")
                    return@forEach
                }
                val path = uri.path ?: return@forEach
                when {
                    DataLayerPaths.matchesPrefix(path, DataLayerPaths.SYNC_CANCEL_PREFIX) -> {
                        val cancelledTransactionId = DataLayerPaths.parseTransactionId(
                            path,
                            DataLayerPaths.SYNC_CANCEL_PREFIX
                        )
                        cancelledTransactionId?.let(::cancelBackupTransaction)
                    }

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

                            if (tid in rejectedBackupTransactions) {
                                Log.w("DataLayerSync", "Ignoring SYNC_REQUEST for rejected transaction: $tid")
                                return@forEach
                            }

                            val isEndpointProbe = dataMap.getBoolean("endpointProbe", false)
                            if (!isEndpointProbe) {
                                // More profile transactions follow this one: the sync overlay must
                                // stay up instead of dropping back to the watch UI between them.
                                followUpTransactionId =
                                    if (dataMap.getBoolean("hasFollowUp", false)) tid else null
                                // Keep the service alive while a real backup is being received.
                                DataLayerSyncForegroundHelper.startIfNeeded(this@DataLayerListenerService)
                                notifySyncStarted()
                                if (!hasStartedSync && currentTransactionId == null) {
                                    syncRequestStartDeadline.onRequest(tid)
                                }
                                sendBroadcast(
                                    Intent(INTENT_ID).apply {
                                        putExtra(APP_BACKUP_PROGRESS_UPDATE, "0.0")
                                        putExtra(APP_BACKUP_PHASE_UPDATE, SyncPhase.CONNECTING.name)
                                        setPackage(packageName)
                                    }
                                )
                            }
                            scope.launch {
                                try {
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

                    DataLayerPaths.matchesPrefix(path, DataLayerPaths.EXERCISE_MOVEMENT_START_PREFIX) ||
                        DataLayerPaths.matchesPrefix(path, DataLayerPaths.EXERCISE_MOVEMENT_CHUNK_PREFIX) -> {
                        val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                        handleExerciseMovementDataItem(path, dataMap)
                    }

                    // Profile list and selection published by the phone.
                    DataLayerPaths.matchesPrefix(path, DataLayerPaths.PROFILE_INDEX_PATH) -> {
                        val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                        dataMap.getString("indexJson")?.let { indexJson ->
                            scope.launch(Dispatchers.IO) {
                                Profiles.applyRemoteIndexJson(applicationContext, indexJson)
                                // A watch with nothing stored yet has no state to invalidate, so
                                // it adopts the phone's selection instead of binding to its own
                                // empty default profile.
                                if (!Profiles.hasStoredData(
                                        applicationContext,
                                        Profiles.activeProfileId(applicationContext),
                                    )
                                ) {
                                    Profiles.alignActiveProfileWithPhone(applicationContext)
                                }
                                // The phone only pushes the profile it is showing, so tell it
                                // which profile this watch follows. A freshly installed watch
                                // has never done that, and otherwise receives nothing.
                                val localProfileId = Profiles.activeProfileId(applicationContext)
                                val hasData = Profiles.hasStoredData(applicationContext, localProfileId)
                                // Announce when we disagree, and also when we have nothing yet:
                                // the phone only pushes in response to a binding, so a fresh watch
                                // would otherwise wait for the next unrelated phone edit.
                                if (!hasData || localProfileId != Profiles.remoteActiveProfileId(applicationContext)) {
                                    publishProfileBinding(applicationContext, localProfileId)
                                }
                            }
                        }
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
                                val payloadProfileId = dataMap.getString(PROFILE_ID_KEY)
                                val appliesToThisWatch = payloadProfileId == null ||
                                    payloadProfileId == Profiles.activeProfileId(this@DataLayerListenerService)
                                if (appliesToThisWatch) {
                                    workoutStoreRepository.saveWorkoutStoreFromJson(workoutStoreJson)
                                    val intent = Intent(INTENT_ID).apply {
                                        putExtra(WORKOUT_STORE_JSON, workoutStoreJson)
                                        setPackage(packageName)
                                    }
                                    sendBroadcast(intent)
                                } else {
                                    Log.d(
                                        "DataLayerSync",
                                        "Ignoring workout store for profile $payloadProfileId; this watch uses " +
                                            Profiles.activeProfileId(this@DataLayerListenerService)
                                    )
                                }

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
                            val timestampStr = dataMap.getString("timestamp")

                            val eventType = if (isStart) "app_backup_start" else "app_backup_chunk"
                            if (shouldIgnoreBackupEvent(
                                    transactionId = transactionId,
                                    timestampStr = timestampStr,
                                    isRetry = isRetry,
                                    eventType = eventType,
                                    ignoreUntilStartOrEnd = ignoreUntilStartOrEnd
                                ) || !pinIncomingBackupProfile(transactionId, dataMap)
                            ) {
                                return@forEach
                            }

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

                                if (isStart) {
                                    // A new transaction supersedes the active one. Reset old state and
                                    // fall through: the start handling below must initialize this sync,
                                    // otherwise its chunks are ignored waiting for a start that was
                                    // already consumed here.
                                    currentTransactionId?.takeIf { it != transactionId }?.let { supersededId ->
                                        incomingBackupProfiles.remove(supersededId)
                                        rememberRejectedBackupTransaction(supersededId)
                                    }
                                    Log.d(
                                        "DataLayerSync",
                                        "Superseding active sync $currentTransactionId with new transaction: $transactionId"
                                    )
                                    clearBackupChunkState()
                                    expectedChunks = 0
                                    hasStartedSync = false
                                    currentTransactionId = null
                                } else {
                                    val intent = Intent(INTENT_ID).apply {
                                        putExtra(APP_BACKUP_FAILED, APP_BACKUP_FAILED)
                                        setPackage(packageName)
                                    }

                                    sendBroadcast(intent)

                                    clearBackupChunkState()
                                    expectedChunks = 0
                                    hasStartedSync = false
                                    currentTransactionId = null

                                    ignoreUntilStartOrEnd = true
                                    return
                                }
                            }

                            if (isStart) {
                                DataLayerSyncForegroundHelper.startIfNeeded(this@DataLayerListenerService)
                                notifySyncStarted()
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
                                clearBackupChunkState()
                                expectedChunks = 0
                                }

                                Log.d(
                                    "DataLayerSync",
                                    "Backup started with expected chunks: $expectedChunks, transactionId: $transactionId"
                                )

                                resetBackupChunkState(transactionId)
                                syncRequestStartDeadline.onBackupStarted()
                                hasStartedSync = true
                                ignoreUntilStartOrEnd = false
                                currentTransactionId = transactionId

                                // Send backup start broadcast (may be duplicate if sync request already triggered it, but that's okay)
                                val intent = Intent(INTENT_ID).apply {
                                    putExtra(APP_BACKUP_START_JSON, APP_BACKUP_START_JSON)
                                    putExtra(APP_BACKUP_START_ACCEPTED, true)
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
                                val chunkTransactionId = transactionId ?: currentTransactionId
                                val remainingChunks =
                                    expectedChunks - receivedBackupChunkCount(chunkTransactionId)
                                postTimeout(maxOf(remainingChunks, 1)) // At least 1 to ensure timeout is set
                                if (isRetry) {
                                    removeRetryTimeout()
                                    postRetryTimeout(maxOf(expectedChunks, 1))
                                }

                                // Handle chunk with index
                                if (chunkIndex >= 0) {
                                    storeReceivedBackupChunk(
                                        chunkTransactionId,
                                        chunkIndex,
                                        backupChunk,
                                    )
                                    Log.d(
                                        "DataLayerSync",
                                        "Received chunk at index $chunkIndex. Total chunks: " +
                                            "${receivedBackupChunkCount(chunkTransactionId)}, " +
                                            "expected: $expectedChunks, isRetry: $isRetry"
                                    )
                                } else {
                                    // Fallback for backwards compatibility - should not happen with new implementation
                                    Log.w(
                                        "DataLayerSync",
                                        "Received chunk without index! Falling back to append behavior."
                                    )
                                    storeReceivedBackupChunk(
                                        chunkTransactionId,
                                        nextBackupChunkIndex(chunkTransactionId),
                                        backupChunk,
                                    )
                                }

                                val progress =
                                    receivedBackupChunkCount(chunkTransactionId).toFloat() /
                                        expectedChunks

                                val progressIntent = Intent(INTENT_ID).apply {
                                    putExtra(APP_BACKUP_PROGRESS_UPDATE, "$progress")
                                    putExtra(
                                        APP_BACKUP_PHASE_UPDATE,
                                        SyncPhase.TRANSFERRING.name
                                    )
                                    setPackage(packageName)
                                }
                                transactionId?.let { tid ->
                                    enqueueSyncProgress(tid, progress, progressIntent)
                                } ?: sendBroadcast(progressIntent)
                            }

                            if (isLastChunk || isLastRetryChunk) {
                                Log.d(
                                    "DataLayerSync",
                                    "Received last backup chunk (isLastChunk: $isLastChunk, " +
                                        "isLastRetryChunk: $isLastRetryChunk). Total chunks received: " +
                                        "${receivedBackupChunkCount(transactionId ?: currentTransactionId)}, " +
                                        "expected: $expectedChunks"
                                )
                                if (!ignoreUntilStartOrEnd) {
                                    removeTimeout()

                                    val processingIntent = Intent(INTENT_ID).apply {
                                        putExtra(APP_BACKUP_PROGRESS_UPDATE, "1.0")
                                        putExtra(
                                            APP_BACKUP_PHASE_UPDATE,
                                            SyncPhase.PROCESSING.name
                                        )
                                        setPackage(packageName)
                                    }
                                    backupProcessingJob = scope.launch(Dispatchers.IO) {
                                        // Snapshot the transaction's transfer state so a superseding
                                        // sync resetting it mid-processing cannot corrupt validation
                                        // or chunk combination.
                                        val processingChunks = snapshotBackupChunks(transactionId)
                                        val processingReceivedIndices =
                                            snapshotReceivedBackupChunkIndices(transactionId)
                                        val processingExpectedChunks = expectedChunks
                                        activeProcessingTransactionId = transactionId
                                        var processingStep = "initialization"
                                        try {
                                            val pendingProgress = synchronized(syncProgressDispatchLock) {
                                                syncProgressDispatchJob
                                            }
                                            pendingProgress?.join()
                                            transactionId?.let { tid ->
                                                publishSyncPhaseAndWaitForPhone(
                                                    transactionId = tid,
                                                    phase = SyncPhase.PROCESSING,
                                                ) {
                                                    val processingPath = DataLayerPaths.buildPath(
                                                        DataLayerPaths.SYNC_PHASE_PREFIX,
                                                        tid
                                                    )
                                                    val processingPayload =
                                                        SyncPhase.PROCESSING.name.toByteArray(
                                                            Charsets.UTF_8
                                                        )
                                                    val connectedNodes = Tasks.await(
                                                        Wearable.getNodeClient(
                                                            this@DataLayerListenerService
                                                        ).connectedNodes
                                                    )
                                                    connectedNodes.forEach { node ->
                                                        Tasks.await(
                                                            Wearable.getMessageClient(
                                                                this@DataLayerListenerService
                                                            ).sendMessage(
                                                                node.id,
                                                                processingPath,
                                                                processingPayload
                                                            )
                                                        )
                                                    }
                                                }
                                                Log.d(
                                                    "DataLayerSync",
                                                    "Phone displayed PROCESSING phase for transaction $tid"
                                                )
                                            }
                                            sendBroadcast(processingIntent)
                                            processingStep = "validating chunks"
                                            
                                            // Log chunk reception details
                                            val chunkReceptionStartTime = System.currentTimeMillis()
                                            val receivedIndicesList = processingReceivedIndices.sorted()
                                            Log.d(
                                                "DataLayerSync",
                                                "Chunk validation for transaction: $transactionId - Expected: $processingExpectedChunks, Received: ${processingChunks.size}, Received indices: $receivedIndicesList"
                                            )
                                            
                                            // Check connection state during validation - fail fast if disconnected
                                            val isConnected = checkConnectionDuringSync(transactionId)
                                            if (!isConnected) {
                                                throw IllegalStateException("Connection lost during chunk validation for transaction: $transactionId")
                                            }

                                            // Validate that all expected chunks are present
                                            val missingIndices = mutableListOf<Int>()
                                            for (i in 0 until processingExpectedChunks) {
                                                if (i !in processingReceivedIndices) {
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
                                                    "Validation failed: Missing chunks. Expected: $processingExpectedChunks, Received: ${processingChunks.size}, Missing indices: $missingIndices, Validation time: ${validationTime}ms"
                                                )
                                                // Log chunk delivery metrics
                                                val deliveryRate = (processingChunks.size.toFloat() / processingExpectedChunks * 100).toInt()
                                                Log.e(
                                                    "DataLayerSync",
                                                    "Chunk delivery metrics - Delivery rate: $deliveryRate%, Missing: ${missingIndices.size}, Transaction: $transactionId"
                                                )

                                                // Send SYNC_ERROR with missing chunk information
                                                transactionId?.let { tid ->
                                                    try {
                                                        val errorMessage =
                                                            "MISSING_CHUNKS: Expected $processingExpectedChunks chunks, received ${processingChunks.size}. Missing indices: $missingIndices"
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
                                                postRetryTimeout(maxOf(processingExpectedChunks, 1))
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
                                                "All chunks validated. Combining ${processingChunks.size} chunks for transaction: $transactionId"
                                            )

                                            // Combine chunks in index order
                                            val sortedChunks =
                                                (0 until processingExpectedChunks).mapNotNull { index ->
                                                    processingChunks[index]
                                                }

                                            if (sortedChunks.size != processingExpectedChunks) {
                                                throw IllegalStateException("Expected $processingExpectedChunks chunks but only ${sortedChunks.size} found after validation")
                                            }

                                            val backupData = combineChunks(sortedChunks)

                                            processingStep = "decompressing backup data"
                                            Log.d(
                                                "DataLayerSync",
                                                "Decompressing backup data (size: ${backupData.size} bytes) for transaction: $transactionId"
                                            )
                                            val jsonBackup = decompressToString(backupData)
                                            postProcessingTimeout(jsonBackup.length)

                                            processingStep = "parsing JSON backup"
                                            Log.d(
                                                "DataLayerSync",
                                                "Parsing JSON backup (length: ${jsonBackup.length} chars) for transaction: $transactionId"
                                            )
                                            val appBackup = fromJSONtoAppBackup(jsonBackup)
                                                .normalizedWorkoutHistories()

                                            val pinnedProfile = transactionId?.let(incomingBackupProfiles::get)
                                            val targetProfileId = if (pinnedProfile != null) {
                                                val backupProfileName = appBackup.ProfileName
                                                require(appBackup.ProfileId == null || appBackup.ProfileId == pinnedProfile.id) {
                                                    "Backup body profile ID does not match the transaction start"
                                                }
                                                require(backupProfileName == null ||
                                                    backupProfileName.trim() == pinnedProfile.name
                                                ) { "Backup body profile name does not match the transaction start" }
                                                pinnedProfile.id
                                            } else {
                                                Profiles.ensureIncomingBackupProfile(
                                                    this@DataLayerListenerService,
                                                    appBackup.ProfileId,
                                                    appBackup.ProfileName,
                                                ) ?: error("Backup profile ID/name is missing or invalid")
                                            }
                                            Log.d(
                                                "DataLayerSync",
                                                "Applying backup tx=$transactionId to profile=$targetProfileId " +
                                                    "activeProfile=${Profiles.activeProfileId(this@DataLayerListenerService)}",
                                            )
                                            val targetDatabase = AppDatabase.getDatabase(
                                                this@DataLayerListenerService,
                                                targetProfileId,
                                            )
                                            val targetWorkoutHistoryDao = targetDatabase.workoutHistoryDao()
                                            val targetSetHistoryDao = targetDatabase.setHistoryDao()
                                            val targetRestHistoryDao = targetDatabase.restHistoryDao()
                                            val targetExerciseInfoDao = targetDatabase.exerciseInfoDao()
                                            val targetWorkoutScheduleDao = targetDatabase.workoutScheduleDao()
                                            val targetWorkoutRecordDao = targetDatabase.workoutRecordDao()
                                            val targetExerciseSessionProgressionDao =
                                                targetDatabase.exerciseSessionProgressionDao()
                                            val targetWorkoutStoreRepository = WorkoutStoreRepository(
                                                Profiles.directory(this@DataLayerListenerService, targetProfileId),
                                                filesDir,
                                            )

                                            processingStep = "saving workout store"
                                            // The phone omits the store when this watch already has
                                            // that exact fingerprint; then WorkoutStore is a placeholder.
                                            val payloadHasWorkoutStore =
                                                appBackup.IncludeWorkoutStore != false
                                            Log.d(
                                                "DataLayerSync",
                                                "Saving workout store for transaction: $transactionId " +
                                                    "(payload includes store: $payloadHasWorkoutStore)"
                                            )
                                            if (payloadHasWorkoutStore) {
                                                restoreExerciseMovementBackups(
                                                    context = this@DataLayerListenerService,
                                                    movementBackups = appBackup.ExerciseMovements.orEmpty()
                                                )
                                                requireExerciseMovementPayloads(
                                                    this@DataLayerListenerService,
                                                    appBackup.WorkoutStore,
                                                )
                                                targetWorkoutStoreRepository.saveWorkoutStore(appBackup.WorkoutStore)
                                            }

                                            processingStep = "database operations"
                                            runBlocking {
                                                var applyLap = System.currentTimeMillis()
                                                fun lap(name: String) {
                                                    val now = System.currentTimeMillis()
                                                    Log.d("DataLayerSync", "applyTiming $name ${now - applyLap}ms")
                                                    applyLap = now
                                                }
                                                // Cleanup protection must reflect the store the watch
                                                // actually holds when the payload omitted it.
                                                val workoutsForCleanup = if (payloadHasWorkoutStore) {
                                                    appBackup.WorkoutStore.workouts
                                                } else {
                                                    targetWorkoutStoreRepository.getWorkoutStore().workouts
                                                }
                                                val allSchedules =
                                                    targetWorkoutScheduleDao.getAllSchedules()

                                                val scheduler = WorkoutAlarmScheduler(context)
                                                for (schedule in allSchedules) {
                                                    scheduler.cancelSchedule(schedule)
                                                }
                                                lap("cancelSchedules")

                                                // Single DB transaction: parallel scope jobs could leave readers
                                                // (e.g. deleteOrphanedRecords) not seeing workout_history rows yet, which
                                                // wiped all workout_record rows and hid Resume on Wear.
                                                withContext(NonCancellable) {
                                                    targetDatabase.withTransaction {
                                                        targetWorkoutScheduleDao.deleteAll()
                                                        targetExerciseSessionProgressionDao.deleteAll()

                                                        // Active workout histories referenced by incoming records
                                                        // must be authoritative during phone->wear full backup sync.
                                                        val activeHistoryIds = appBackup.WorkoutRecords
                                                            .map { it.workoutHistoryId }
                                                            .toSet()
                                                        val (activeHistories, regularHistories) =
                                                            appBackup.WorkoutHistories.partition { history ->
                                                                history.id in activeHistoryIds
                                                            }

                                                        if (activeHistories.isNotEmpty()) {
                                                            targetWorkoutHistoryDao.insertAll(*activeHistories.toTypedArray())
                                                        }
                                                        if (regularHistories.isNotEmpty()) {
                                                            targetWorkoutHistoryDao.insertAllWithVersionCheck(
                                                                *regularHistories.toTypedArray()
                                                            )
                                                        }
                                                        lap("histories")

                                                        targetSetHistoryDao.insertAllWithVersionCheck(
                                                            *appBackup.SetHistories.toTypedArray()
                                                        )
                                                        lap("sets")

                                                        val rests = appBackup.RestHistories.orEmpty()
                                                        if (rests.isNotEmpty()) {
                                                            targetRestHistoryDao.insertAllWithVersionCheck(
                                                                *rests.toTypedArray()
                                                            )
                                                        }

                                                        targetExerciseInfoDao.insertAllWithVersionCheck(
                                                            *appBackup.ExerciseInfos.toTypedArray()
                                                        )
                                                        lap("exerciseInfos")

                                                        targetWorkoutScheduleDao.deleteAll()
                                                        targetWorkoutScheduleDao.insertAll(*appBackup.WorkoutSchedules.toTypedArray())
                                                        lap("schedules")

                                                        val validExerciseSessionProgressions =
                                                            appBackup.ExerciseSessionProgressions.filter { progression ->
                                                                appBackup.WorkoutHistories.any { it.id == progression.workoutHistoryId }
                                                            }
                                                        targetExerciseSessionProgressionDao.insertAll(
                                                            *validExerciseSessionProgressions.toTypedArray()
                                                        )

                                                        lap("progressions")
                                                        cleanupUnusedWorkoutHistories(
                                                            workoutsForCleanup,
                                                            appBackup.WorkoutHistories.map { it.id }.toSet(),
                                                            targetWorkoutHistoryDao,
                                                            targetSetHistoryDao,
                                                            targetExerciseSessionProgressionDao,
                                                        )
                                                        lap("cleanupUnused")
                                                        mergeIncomingWorkoutRecords(
                                                            appBackup,
                                                            targetWorkoutHistoryDao,
                                                            targetWorkoutRecordDao,
                                                        )
                                                        lap("mergeRecords")
                                                        targetWorkoutRecordDao.deleteOrphanedRecords()
                                                        lap("deleteOrphaned")
                                                        reconcileActiveRecordsWithHistories(
                                                            targetWorkoutHistoryDao,
                                                            targetWorkoutRecordDao,
                                                        )
                                                    }
                                                    lap("reconcile+commit")
                                                }

                                                // Re-register alarms here so sync completes reliably when MainActivity
                                                // is not running (dynamic WearDataLayerReceiver would not receive APP_BACKUP_END).
                                                WorkoutAlarmScheduler(applicationContext).rescheduleAllWorkouts()
                                                lap("rescheduleAlarms")

                                                val legacyAppInForeground = MyApplication.isAppInForeground()
                                                val processLifecycleState =
                                                    ProcessLifecycleOwner.get().lifecycle.currentState
                                                val shouldPostSyncCompleteNotification =
                                                    !processLifecycleState.isAtLeast(Lifecycle.State.RESUMED)
                                                Log.d(
                                                    TAG,
                                                    "syncCompleteNotification policy show=$shouldPostSyncCompleteNotification " +
                                                        "legacyAppInForeground=$legacyAppInForeground " +
                                                        "processLifecycleState=$processLifecycleState tx=$transactionId"
                                                )
                                                removeTimeout()
                                                clearSyncInProgressNotification()
                                                if (shouldPostSyncCompleteNotification) {
                                                    showSyncCompleteNotification(this@DataLayerListenerService)
                                                }

                                                // Send completion acknowledgment
                                                val completionPublished = transactionId?.let { tid ->
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
                                                        completeDataMapRequest.dataMap.putFloat(
                                                            "progress",
                                                            1f
                                                        )
                                                        completeDataMapRequest.dataMap.putString(
                                                            "phase",
                                                            SyncPhase.COMPLETED.name
                                                        )

                                                        val completeRequest =
                                                            completeDataMapRequest.asPutDataRequest()
                                                                .setUrgent()
                                                        Log.d(
                                                            "DataLayerSync",
                                                            "Sending SYNC_COMPLETE for transaction: $tid, timestamp: $timestamp"
                                                        )
                                                        Tasks.await(
                                                            dataClient.putDataItem(completeRequest)
                                                        )
                                                        Log.d(
                                                            "DataLayerSync",
                                                            "Successfully sent SYNC_COMPLETE for transaction: $tid (backup)"
                                                        )
                                                        true
                                                    } catch (exception: Exception) {
                                                        Log.e(
                                                            "DataLayerSync",
                                                            "Failed to send SYNC_COMPLETE for transaction: $tid",
                                                            exception
                                                        )
                                                        false
                                                    }
                                                } ?: false

                                                check(completionPublished) {
                                                    "Failed to publish SYNC_COMPLETE for transaction: $transactionId"
                                                }

                                                // Dismiss the Wear sync screen only after the processed-data
                                                // acknowledgment has been successfully published to the phone.
                                                syncRequestStartDeadline.cancel(transactionId)
                                                val moreTransactionsFollow =
                                                    transactionId != null && transactionId == followUpTransactionId
                                                if (moreTransactionsFollow) {
                                                    followUpTransactionId = null
                                                }
                                                val intent = Intent(INTENT_ID).apply {
                                                    putExtra(APP_BACKUP_END_JSON, APP_BACKUP_END_JSON)
                                                    putExtra(APP_BACKUP_MORE_COMING, moreTransactionsFollow)
                                                    setPackage(packageName)
                                                }
                                                sendBroadcast(intent)
                                                Log.d(
                                                    "DataLayerSync",
                                                    "Backup completion acknowledged and broadcast sent for transaction: $transactionId"
                                                )

                                                markTransactionCompleted(transactionId)
                                                // Only clear if this transaction is still the active one;
                                                // a superseding sync owns the shared state now.
                                                if (currentTransactionId == transactionId) {
                                                    clearBackupChunkState()
                                                    expectedChunks = 0
                                                    hasStartedSync = false
                                                    ignoreUntilStartOrEnd = false
                                                    currentTransactionId = null
                                                }
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
                                            transactionId?.let { failedId ->
                                                incomingBackupProfiles.remove(failedId)
                                                rememberRejectedBackupTransaction(failedId)
                                            }
                                            removeRetryTimeout()
                                            // Only clear if this transaction is still the active one;
                                            // a superseding sync owns the shared state now.
                                            if (currentTransactionId == transactionId) {
                                                clearBackupChunkState()
                                                expectedChunks = 0
                                                hasStartedSync = false
                                                ignoreUntilStartOrEnd = false
                                                currentTransactionId = null
                                            }

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
                                        } finally {
                                            if (activeProcessingTransactionId == transactionId) {
                                                activeProcessingTransactionId = null
                                            }
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
            cleanupIncompleteSyncState()
        }
    }

    private fun enqueueSyncProgress(
        transactionId: String,
        progress: Float,
        progressIntent: Intent,
    ) {
        // The watch UI only displays whole percent, so echoing more often than a
        // percent change is pure Data Layer/broadcast cost on a weak CPU.
        val percent = (progress.coerceIn(0f, 1f) * 100f).toInt()
        synchronized(syncProgressDispatchLock) {
            val state = syncProgressEchoStateByTransaction.getOrPut(transactionId) {
                SyncProgressEchoState()
            }
            if (percent <= state.lastEnqueuedPercent) {
                return
            }
            state.lastEnqueuedPercent = percent
            val previous = syncProgressDispatchJob
            syncProgressDispatchJob = scope.launch {
                previous?.join()
                publishSyncProgress(transactionId, progress)
                sendBroadcast(progressIntent)
            }
        }
    }

    private suspend fun publishSyncProgress(
        transactionId: String,
        progress: Float
    ) {
        val normalizedProgress = progress.coerceIn(0f, 1f)
        synchronized(syncProgressDispatchLock) {
            val previousProgress = lastPublishedProgressByTransaction[transactionId]
            if (previousProgress != null && normalizedProgress <= previousProgress) {
                return
            }
            if (normalizedProgress >= 1f) {
                lastPublishedProgressByTransaction.remove(transactionId)
            } else {
                lastPublishedProgressByTransaction[transactionId] = normalizedProgress
            }
        }

        val progressPath = DataLayerPaths.buildPath(
            DataLayerPaths.SYNC_PROGRESS_PREFIX,
            transactionId
        )
        val payload = SyncProgressUpdate(
            phase = SyncPhase.TRANSFERRING,
            progress = normalizedProgress
        ).toByteArray()

        try {
            val targetNodeIds = connectedNodeIdsForSyncProgress(transactionId)
            check(targetNodeIds.isNotEmpty()) {
                "No phone node available for sync progress transaction $transactionId"
            }
            targetNodeIds.forEach { nodeId ->
                Tasks.await(
                    Wearable.getMessageClient(this@DataLayerListenerService).sendMessage(
                        nodeId,
                        progressPath,
                        payload
                    )
                )
            }
            Log.d(
                "DataLayerSync",
                "Published acknowledged progress $normalizedProgress for transaction $transactionId " +
                    "to nodes=$targetNodeIds"
            )
        } catch (exception: Exception) {
            Log.w(
                "DataLayerSync",
                "Failed to publish acknowledged progress for transaction $transactionId",
                exception
            )
            // The node set may have changed; re-resolve on the next throttled echo.
            invalidateSyncProgressNodes(transactionId)
        }
    }

    /** Cached for the transaction so each percent echo does not await GMS again. */
    private suspend fun connectedNodeIdsForSyncProgress(transactionId: String): List<String> {
        synchronized(syncProgressDispatchLock) {
            syncProgressEchoStateByTransaction[transactionId]?.connectedNodeIds?.let {
                return it
            }
        }
        val nodeIds = Tasks.await(
            Wearable.getNodeClient(this@DataLayerListenerService).connectedNodes
        ).map { node -> node.id }
        synchronized(syncProgressDispatchLock) {
            syncProgressEchoStateByTransaction.getOrPut(transactionId) {
                SyncProgressEchoState()
            }.connectedNodeIds = nodeIds
        }
        return nodeIds
    }

    private fun invalidateSyncProgressNodes(transactionId: String) {
        synchronized(syncProgressDispatchLock) {
            syncProgressEchoStateByTransaction[transactionId]?.connectedNodeIds = null
        }
    }

    private fun clearSyncProgressState(transactionId: String?) {
        if (transactionId == null) return
        synchronized(syncProgressDispatchLock) {
            syncProgressEchoStateByTransaction.remove(transactionId)
            lastPublishedProgressByTransaction.remove(transactionId)
        }
    }

    /**
     * Cleans up workout histories that are no longer needed for plateau detection.
     * Keeps only the most recent 15 workout histories per exercise (same as phone sync logic)
     * plus any workout histories that were just synced.
     */
    private suspend fun cleanupUnusedWorkoutHistories(
        workouts: List<Workout>,
        syncedWorkoutHistoryIds: Set<UUID>,
        workoutHistoryDao: WorkoutHistoryDao,
        setHistoryDao: SetHistoryDao,
        exerciseSessionProgressionDao: ExerciseSessionProgressionDao,
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
            // Read set histories once: one query per exercise meant hundreds of full scans.
            val setHistoriesByExerciseId = setHistoryDao.getAllSetHistories().groupBy { it.exerciseId }
            for (exercise in allExercises) {
                val workoutHistoryIds = setHistoriesByExerciseId[exercise.id].orEmpty()
                    .mapNotNull { it.workoutHistoryId }
                    .distinct()

                if (workoutHistoryIds.isNotEmpty()) {
                    // Same window the phone sends; anything older cannot be read by plateau
                    // detection (3 non-deload sessions, 4 minimum, 30-day cutoff).
                    val workoutHistoriesForExercise = allWorkoutHistories
                        .filter { it.id in workoutHistoryIds }
                        .sortedByDescending { it.startTime }
                        .take(SyncHistoryRetention.SESSIONS_PER_EXERCISE)

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

    private suspend fun mergeIncomingWorkoutRecords(
        appBackup: com.gabstra.myworkoutassistant.shared.AppBackup,
        workoutHistoryDao: WorkoutHistoryDao,
        workoutRecordDao: WorkoutRecordDao,
    ) {
        val existingHistoriesById = workoutHistoryDao.getAllWorkoutHistories().associateBy { it.id }
        val existingRecords = workoutRecordDao.getAll()
        val incomingHistoriesById = appBackup.WorkoutHistories.associateBy { it.id }
        val mergedRecords = mergeWorkoutRecordsForBackup(
            existingRecords = existingRecords,
            existingHistoriesById = existingHistoriesById,
            incomingRecords = appBackup.WorkoutRecords,
            incomingHistoriesById = incomingHistoriesById
        )

        workoutRecordDao.deleteAll()
        if (mergedRecords.isNotEmpty()) {
            workoutRecordDao.insertAll(*mergedRecords.toTypedArray())
        }
    }

    private suspend fun reconcileActiveRecordsWithHistories(
        workoutHistoryDao: WorkoutHistoryDao,
        workoutRecordDao: WorkoutRecordDao,
    ) {
        workoutRecordDao.getAll().forEach { record ->
            val history = workoutHistoryDao.getWorkoutHistoryById(record.workoutHistoryId) ?: return@forEach
            if (history.isDone) {
                workoutHistoryDao.updateIsDone(history.id, isDone = false)
            }
        }
    }

    override fun onDestroy() {
        if (activeService === this) {
            activeService = null
            removeTimeout()
            removeRetryTimeout()
        }
        (syncRequestStartDeadline.cancel() as? SyncRequestStartDeadline.Cancellation.Cancelled)?.let {
            Log.w("DataLayerSync", "Service destroyed before backup start: ${it.transactionId}")
            sendBackupFailedBroadcast()
        }
        DataLayerSyncForegroundHelper.stopIfActive(this)
        pendingSyncPhaseAcks.values.forEach { it.cancel() }
        pendingSyncPhaseAcks.clear()
        super.onDestroy()
        scope.cancel()
    }

    companion object {
        private val lastPublishedProgressByTransaction = mutableMapOf<String, Float>()
        private const val TAG = "DataLayerListenerService"
        private const val SYNC_PHASE_ACK_TIMEOUT_MS = 5_000L
        private const val MAX_COMPLETED_TRANSACTION_IDS = 128
        private const val PREFS_COMPLETED_ORDERED = "completedTransactionIdsOrdered"
        private const val LEGACY_BACKUP_CHUNKS_KEY = "backup_chunks"
        private const val LEGACY_RECEIVED_CHUNK_INDICES_KEY = "receivedChunkIndices"
        private const val LOCAL_NODE_RESOLUTION_ATTEMPTS = 3
        private const val LOCAL_NODE_RESOLUTION_TIMEOUT_MS = 2_000L
        private const val LOCAL_NODE_RESOLUTION_RETRY_DELAY_MS = 500L

        // Process-wide so a service re-bind (new instance, same process) can tell
        // "backup processing still running" apart from "process died mid-sync";
        // only the latter should trigger auto-heal.
        @Volatile
        var activeProcessingTransactionId: String? = null

        // Transaction whose completion is followed by another profile transaction in the same
        // phone sync; its end must not dismiss the watch sync overlay.
        @Volatile
        var followUpTransactionId: String? = null

        // One deadline scheduler for the whole process. A re-bind creates a new service
        // instance while the previous instance's callbacks are still queued on the (shared)
        // main looper; per-instance Runnables could not be cancelled from the instance that
        // took over, so stale deadlines fired and failed syncs that were completing.
        private val syncHandler = Handler(Looper.getMainLooper())

        @Volatile
        private var activeService: DataLayerListenerService? = null

        private val completionTimeoutRunnable = Runnable {
            val service = activeService
            if (service == null) {
                Log.d(TAG, "Timeout fired with no active service; ignoring")
            } else {
                service.handleCompletionTimeout()
            }
        }

        private val retryTimeoutRunnable = Runnable {
            activeService?.handleRetryTimeout()
        }

        // False until the first onCreate in this process; a later onCreate is a
        // re-bind of the same process, not a service restart.
        @Volatile
        var serviceCreatedInThisProcess = false

        const val CLEAR_ERROR_LOGS_PATH = "/clearErrorLogs"
        const val ERROR_LOGS_SYNC_PATH = "/errorLogsSync"
        const val INTENT_ID = "com.gabstra.myworkoutassistant.workoutstore"
        const val WORKOUT_STORE_JSON = "workoutStoreJson"
        const val APP_BACKUP_START_JSON = "appBackupStartJson"
        const val APP_BACKUP_START_ACCEPTED = "appBackupStartAccepted"
        const val APP_BACKUP_END_JSON = "appBackupEndJson"
        const val APP_BACKUP_MORE_COMING = "appBackupMoreComing"
        const val APP_BACKUP_FAILED = "appBackupFailed"
        const val APP_BACKUP_PROGRESS_UPDATE = "progress_update"
        const val APP_BACKUP_PHASE_UPDATE = "phase_update"
        const val SYNC_COMPLETE = "syncComplete"
        const val TRANSACTION_ID = "transactionId"
        const val HANDSHAKE_TIMEOUT_MS = 15000L // Increased from 5000L for slow connections
        const val SYNC_REQUEST_START_TIMEOUT_MS = 60_000L
        const val COMPLETION_TIMEOUT_MS =
            30000L // Legacy constant, use calculateCompletionTimeout instead
        const val BASE_COMPLETION_TIMEOUT_MS = 10000L
        const val PER_CHUNK_TIMEOUT_MS = 2000L
        const val MAX_COMPLETION_TIMEOUT_MS = 300000L // 5 minutes

        // Local processing (gunzip + JSON parse + DB apply) scales with payload size, not with
        // chunk count: ~21s for a 4.5M-char backup on Wear-class hardware.
        private const val PROCESSING_BASE_TIMEOUT_MS = 30000L
        private const val PROCESSING_TIMEOUT_PER_MEGACHAR_MS = 30000L
        
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
                prefs.edit {
                    putFloat(PREF_CONNECTION_QUALITY, multiplier)
                }
                Log.d("DataLayerSync", "Updated connection quality multiplier to $multiplier (timeout rate: $timeoutRate)")
            }
        }
    }
}
