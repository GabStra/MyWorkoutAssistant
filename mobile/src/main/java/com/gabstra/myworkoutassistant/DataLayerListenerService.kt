package com.gabstra.myworkoutassistant

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.util.Log
import android.widget.Toast
import androidx.core.content.edit
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.ErrorLog
import com.gabstra.myworkoutassistant.shared.ErrorLogDao
import com.gabstra.myworkoutassistant.shared.ExerciseSessionSnapshot
import com.gabstra.myworkoutassistant.shared.ExerciseInfoDao
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgressionDao
import com.gabstra.myworkoutassistant.shared.RestHistoryDao
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryStore
import com.gabstra.myworkoutassistant.shared.WorkoutManager.Companion.replaceSetsInExerciseRecursively
import com.gabstra.myworkoutassistant.shared.WorkoutManager.Companion.updateWorkoutOld
import com.gabstra.myworkoutassistant.shared.WorkoutManager.Companion.updateWorkoutComponentsRecursively
import com.gabstra.myworkoutassistant.shared.WorkoutRecord
import com.gabstra.myworkoutassistant.shared.WorkoutRecordDao
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.adapters.ExerciseSessionSnapshotAdapter
import com.gabstra.myworkoutassistant.shared.adapters.LocalDateAdapter
import com.gabstra.myworkoutassistant.shared.adapters.LocalDateTimeAdapter
import com.gabstra.myworkoutassistant.shared.adapters.LocalTimeAdapter
import com.gabstra.myworkoutassistant.shared.adapters.SetAdapter
import com.gabstra.myworkoutassistant.shared.adapters.SetDataAdapter
import com.gabstra.myworkoutassistant.shared.datalayer.DataLayerPaths
import com.gabstra.myworkoutassistant.shared.datalayer.WorkoutSessionHeartbeat
import com.gabstra.myworkoutassistant.shared.datalayer.WorkoutSessionHeartbeatKeys
import com.gabstra.myworkoutassistant.shared.datalayer.decideWorkoutSessionHeartbeatApply
import com.gabstra.myworkoutassistant.shared.datalayer.sentAtLocalDateTime
import com.gabstra.myworkoutassistant.shared.decompressToString
import com.gabstra.myworkoutassistant.shared.findWorkoutForHistory
import com.gabstra.myworkoutassistant.llm.PhoneLlmOperationExecutor
import com.gabstra.myworkoutassistant.shared.llm.DEFAULT_PHONE_LLM_OPERATION
import com.gabstra.myworkoutassistant.shared.llm.PhoneLlmDataMapKeys
import com.gabstra.myworkoutassistant.shared.llm.PhoneLlmOperationRequest
import com.gabstra.myworkoutassistant.shared.llm.PhoneLlmOperationResult
import com.gabstra.myworkoutassistant.shared.workout.history.ExerciseSessionReconstruction
import com.gabstra.myworkoutassistant.ensureRestSeparatedBySets
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.workout.model.decideWorkoutRecordIngest
import com.gabstra.myworkoutassistant.sync.BackupCoordinator
import com.gabstra.myworkoutassistant.sync.PhoneSyncToWatchSuppressor
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
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
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID
import kotlin.coroutines.cancellation.CancellationException
import kotlin.io.encoding.Base64
import kotlin.io.encoding.ExperimentalEncodingApi

internal object WorkoutHistoryChunkProcessingPolicy {
    fun shouldProcessImmediately(receivedChunks: Int, expectedChunks: Int): Boolean {
        return expectedChunks > 0 && receivedChunks >= expectedChunks
    }

    fun shouldScheduleSettleWindow(
        receivedChunks: Int,
        expectedChunks: Int,
        sawTerminalChunk: Boolean,
        alreadyWaitingForTrailingChunks: Boolean
    ): Boolean {
        if (shouldProcessImmediately(receivedChunks, expectedChunks)) {
            return false
        }
        return sawTerminalChunk || alreadyWaitingForTrailingChunks
    }
}

internal enum class WorkoutHistoryInboundState {
    Idle,
    Receiving,
    WaitingForTrailingChunks,
    Processing
}

internal object WorkoutHistoryInboundStatePolicy {
    fun hasActiveTransaction(state: WorkoutHistoryInboundState): Boolean {
        return state != WorkoutHistoryInboundState.Idle
    }

    fun shouldIgnoreTerminalReplay(isTerminalTransaction: Boolean): Boolean {
        return isTerminalTransaction
    }

    fun shouldResetForDifferentActiveTransaction(
        currentTransactionId: String?,
        currentState: WorkoutHistoryInboundState,
        incomingTransactionId: String?,
        isStart: Boolean,
        hasChunkPayload: Boolean,
        isRetry: Boolean
    ): Boolean {
        if (isRetry) {
            return false
        }
        if (!hasActiveTransaction(currentState)) {
            return hasChunkPayload
        }
        return (isStart && currentTransactionId != null) ||
            (currentTransactionId != null && currentTransactionId != incomingTransactionId) ||
            (hasChunkPayload && currentTransactionId == null)
    }

    fun shouldIgnoreStaleRetryChunk(
        isRetry: Boolean,
        retryGeneration: Int,
        latestRequestedRetryGeneration: Int
    ): Boolean {
        if (!isRetry || latestRequestedRetryGeneration <= 0) {
            return false
        }
        return retryGeneration in 1 until latestRequestedRetryGeneration
    }
}

internal data class WorkoutHistorySyncTelemetrySnapshot(
    val requestedRetryGenerations: Int = 0,
    val staleRetryChunksIgnored: Int = 0,
    val transactionsRecoveredAfterRetry: Int = 0
)

internal object WorkoutHistorySyncTelemetryPolicy {
    fun recordRetryRequested(
        snapshot: WorkoutHistorySyncTelemetrySnapshot
    ): WorkoutHistorySyncTelemetrySnapshot {
        return snapshot.copy(
            requestedRetryGenerations = snapshot.requestedRetryGenerations + 1
        )
    }

    fun recordStaleRetryIgnored(
        snapshot: WorkoutHistorySyncTelemetrySnapshot
    ): WorkoutHistorySyncTelemetrySnapshot {
        return snapshot.copy(
            staleRetryChunksIgnored = snapshot.staleRetryChunksIgnored + 1
        )
    }

    fun recordRecoveredAfterRetry(
        snapshot: WorkoutHistorySyncTelemetrySnapshot,
        latestRequestedRetryGeneration: Int
    ): WorkoutHistorySyncTelemetrySnapshot {
        if (latestRequestedRetryGeneration <= 0) {
            return snapshot
        }
        return snapshot.copy(
            transactionsRecoveredAfterRetry = snapshot.transactionsRecoveredAfterRetry + 1
        )
    }

    fun toLogLine(
        snapshot: WorkoutHistorySyncTelemetrySnapshot,
        transactionId: String?,
        reason: String
    ): String {
        return "SYNC_TELEMETRY side=mobile tx=$transactionId reason=$reason " +
            "retryRequests=${snapshot.requestedRetryGenerations} " +
            "staleRetryChunksIgnored=${snapshot.staleRetryChunksIgnored} " +
            "transactionsRecoveredAfterRetry=${snapshot.transactionsRecoveredAfterRetry}"
    }
}

class DataLayerListenerService : WearableListenerService() {
    private val dataClient by lazy { Wearable.getDataClient(this) }
    private val nodeClient by lazy { Wearable.getNodeClient(this) }
    @Volatile
    private var localNodeId: String? = null

    private val workoutStoreRepository by lazy { WorkoutStoreRepository(this.filesDir) }
    private val phoneLlmOperationExecutor by lazy { PhoneLlmOperationExecutor(this) }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private lateinit var workoutHistoryDao: WorkoutHistoryDao
    private lateinit var setHistoryDao: SetHistoryDao
    private lateinit var restHistoryDao: RestHistoryDao
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
        .registerTypeAdapter(Set::class.java, SetAdapter())
        .registerTypeAdapter(SetData::class.java, SetDataAdapter())
        .registerTypeAdapter(BodyWeightSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(EnduranceSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(TimedDurationSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(RestSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(WeightSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(ExerciseSessionSnapshot::class.java, ExerciseSessionSnapshotAdapter())
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

    private var currentTransactionState: WorkoutHistoryInboundState
        get() {
            val stored = sharedPreferences.getString("current_workout_history_state", null)
            return runCatching {
                if (stored.isNullOrBlank()) {
                    WorkoutHistoryInboundState.Idle
                } else {
                    enumValueOf<WorkoutHistoryInboundState>(stored)
                }
            }.getOrElse {
                sharedPreferences.edit { remove("current_workout_history_state") }
                WorkoutHistoryInboundState.Idle
            }
        }
        set(value) {
            sharedPreferences.edit { putString("current_workout_history_state", value.name) }
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

    private var latestRequestedRetryGeneration: Int
        get() = sharedPreferences.getInt("latest_requested_retry_generation", 0)
        set(value) {
            sharedPreferences.edit { putInt("latest_requested_retry_generation", value) }
        }

    private var workoutHistorySyncTelemetrySnapshot: WorkoutHistorySyncTelemetrySnapshot
        get() {
            val jsonString = sharedPreferences.getString("workout_history_sync_telemetry", null)
            if (jsonString.isNullOrEmpty()) {
                return WorkoutHistorySyncTelemetrySnapshot()
            }
            return runCatching {
                gson.fromJson(
                    jsonString,
                    WorkoutHistorySyncTelemetrySnapshot::class.java
                ) ?: WorkoutHistorySyncTelemetrySnapshot()
            }.getOrElse {
                sharedPreferences.edit { remove("workout_history_sync_telemetry") }
                WorkoutHistorySyncTelemetrySnapshot()
            }
        }
        set(value) {
            sharedPreferences.edit {
                putString("workout_history_sync_telemetry", gson.toJson(value))
            }
        }

    private var terminalTransactionTimestamps: MutableMap<String, Long>
        get() {
            val jsonString =
                sharedPreferences.getString("terminal_workout_history_transactions", null)
            if (jsonString.isNullOrEmpty()) {
                return mutableMapOf()
            }
            return try {
                val typeToken = object : TypeToken<Map<String, Long>>() {}.type
                gson.fromJson<Map<String, Long>>(jsonString, typeToken)?.toMutableMap()
                    ?: mutableMapOf()
            } catch (e: Exception) {
                Log.e(
                    "DataLayerListenerService",
                    "Failed to parse terminal transaction cache: ${e.message}",
                    e
                )
                sharedPreferences.edit { remove("terminal_workout_history_transactions") }
                mutableMapOf()
            }
        }
        set(value) {
            if (value.isEmpty()) {
                sharedPreferences.edit { remove("terminal_workout_history_transactions") }
            } else {
                sharedPreferences.edit {
                    putString("terminal_workout_history_transactions", gson.toJson(value))
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

    private var pendingWorkoutHistoryProcessingJob: Job? = null

    private fun cancelPendingWorkoutHistoryProcessing() {
        pendingWorkoutHistoryProcessingJob?.cancel()
        pendingWorkoutHistoryProcessingJob = null
    }

    private fun clearActiveWorkoutHistoryTransactionState() {
        workoutHistoryChunks = mutableMapOf()
        receivedChunkIndices = mutableSetOf()
        expectedChunks = 0
        latestRequestedRetryGeneration = 0
        hasStartedSync = false
        ignoreUntilStartOrEnd = false
        currentTransactionId = null
        currentTransactionState = WorkoutHistoryInboundState.Idle
        cancelPendingWorkoutHistoryProcessing()
    }

    private fun pruneTerminalTransactions(now: Long = System.currentTimeMillis()) {
        val current = terminalTransactionTimestamps
        val pruned = current.filterValues { timestamp ->
            now - timestamp <= TERMINAL_TRANSACTION_TTL_MS
        }.toMutableMap()
        if (pruned.size != current.size) {
            terminalTransactionTimestamps = pruned
        }
    }

    private fun isTerminalTransaction(transactionId: String?): Boolean {
        if (transactionId.isNullOrBlank()) return false
        pruneTerminalTransactions()
        return terminalTransactionTimestamps.containsKey(transactionId)
    }

    private fun markTerminalTransaction(transactionId: String?) {
        if (transactionId.isNullOrBlank()) return
        pruneTerminalTransactions()
        val updated = terminalTransactionTimestamps
        updated[transactionId] = System.currentTimeMillis()
        terminalTransactionTimestamps = updated
    }

    private fun scheduleWorkoutHistoryProcessing(transactionId: String?) {
        cancelPendingWorkoutHistoryProcessing()
        currentTransactionState = WorkoutHistoryInboundState.WaitingForTrailingChunks
        pendingWorkoutHistoryProcessingJob = scope.launch(Dispatchers.IO) {
            delay(WORKOUT_HISTORY_CHUNK_SETTLE_MS)
            processReceivedWorkoutHistory(transactionId)
        }
    }

    private fun launchWorkoutHistoryProcessing(transactionId: String?) {
        cancelPendingWorkoutHistoryProcessing()
        currentTransactionState = WorkoutHistoryInboundState.Processing
        pendingWorkoutHistoryProcessingJob = scope.launch(Dispatchers.IO) {
            processReceivedWorkoutHistory(transactionId)
        }
    }

    private fun updateWorkoutHistorySyncTelemetry(
        transactionId: String?,
        reason: String,
        update: (WorkoutHistorySyncTelemetrySnapshot) -> WorkoutHistorySyncTelemetrySnapshot
    ) {
        val updatedSnapshot = update(workoutHistorySyncTelemetrySnapshot)
        workoutHistorySyncTelemetrySnapshot = updatedSnapshot
        Log.d(
            "WorkoutSync",
            WorkoutHistorySyncTelemetryPolicy.toLogLine(
                snapshot = updatedSnapshot,
                transactionId = transactionId,
                reason = reason
            )
        )
    }

    private suspend fun processReceivedWorkoutHistory(transactionId: String?) {
        PhoneSyncToWatchSuppressor.enterWearInboundApply()
        try {
            currentTransactionState = WorkoutHistoryInboundState.Processing
            var processingStep = "initialization"
            try {
                processingStep = "validating chunks"
                Log.d("WorkoutSync", "Workout history processing started, transaction: $transactionId")

                val chunkReceptionStartTime = System.currentTimeMillis()
                val receivedIndicesList = receivedChunkIndices.sorted()
                Log.d(
                    "DataLayerSync",
                    "Chunk validation for transaction: $transactionId - Expected: $expectedChunks, Received: ${workoutHistoryChunks.size}, Received indices: $receivedIndicesList"
                )

                val isConnected = checkConnectionDuringSync(transactionId)
                if (!isConnected) {
                    throw IllegalStateException("Connection lost during chunk validation for transaction: $transactionId")
                }

                val missingIndices = mutableListOf<Int>()
                for (i in 0 until expectedChunks) {
                    if (i !in receivedChunkIndices) {
                        missingIndices.add(i)
                    }
                }

                val validationTime = System.currentTimeMillis() - chunkReceptionStartTime
                Log.d(
                    "DataLayerSync",
                    "Chunk validation completed in ${validationTime}ms for transaction: $transactionId"
                )

                val retryGenerationsUsed = latestRequestedRetryGeneration
                if (missingIndices.isNotEmpty()) {
                    val retryGeneration = latestRequestedRetryGeneration + 1
                    latestRequestedRetryGeneration = retryGeneration
                    updateWorkoutHistorySyncTelemetry(
                        transactionId = transactionId,
                        reason = "missing_chunks_requested"
                    ) { snapshot ->
                        WorkoutHistorySyncTelemetryPolicy.recordRetryRequested(snapshot)
                    }
                    Log.e(
                        "DataLayerSync",
                        "Validation failed: Missing chunks. Expected: $expectedChunks, " +
                            "Received: ${workoutHistoryChunks.size}, Missing indices: $missingIndices, " +
                            "retryGeneration=$retryGeneration, Validation time: ${validationTime}ms"
                    )
                    Log.d(
                        "WorkoutSync",
                        "SYNC_TRACE event=missing_chunks side=mobile direction=send tx=$transactionId " +
                            "expected=$expectedChunks received=${workoutHistoryChunks.size} " +
                            "missing=$missingIndices retryGeneration=$retryGeneration"
                    )
                    val deliveryRate = (workoutHistoryChunks.size.toFloat() / expectedChunks * 100).toInt()
                    Log.e(
                        "DataLayerSync",
                        "Chunk delivery metrics - Delivery rate: $deliveryRate%, Missing: ${missingIndices.size}, Transaction: $transactionId"
                    )

                    transactionId?.let { tid ->
                        try {
                            val errorMessage =
                                buildMissingChunksErrorMessage(
                                    expectedChunks = expectedChunks,
                                    receivedChunks = workoutHistoryChunks.size,
                                    missingIndices = missingIndices,
                                    retryGeneration = retryGeneration
                                )
                            Log.e(
                                "DataLayerSync",
                                "Sending SYNC_ERROR for transaction: $tid due to missing chunks"
                            )
                            Log.d(
                                "WorkoutSync",
                                "SYNC_TRACE event=error side=mobile direction=send tx=$tid message=$errorMessage"
                            )
                            val errorPath = DataLayerPaths.buildPath(
                                DataLayerPaths.SYNC_ERROR_PREFIX,
                                tid
                            )
                            val errorDataMapRequest = PutDataMapRequest.create(errorPath)
                            errorDataMapRequest.dataMap.putString("transactionId", tid)
                            errorDataMapRequest.dataMap.putString("errorMessage", errorMessage)
                            errorDataMapRequest.dataMap.putInt("retryGeneration", retryGeneration)
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

                    return
                }

                val isConnectedBeforeProcessing = checkConnectionDuringSync(transactionId)
                if (!isConnectedBeforeProcessing) {
                    throw IllegalStateException("Connection lost before processing for transaction: $transactionId")
                }

                processingStep = "combining chunks"
                Log.d(
                    "DataLayerSync",
                    "All chunks validated. Combining ${workoutHistoryChunks.size} chunks for transaction: $transactionId"
                )

                val sortedChunks = (0 until expectedChunks).mapNotNull { index ->
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
                val workoutHistoryStoreJson = decompressToString(compressedData)

                processingStep = "parsing JSON workout history"
                Log.d(
                    "DataLayerSync",
                    "Parsing JSON workout history (length: ${workoutHistoryStoreJson.length} chars) for transaction: $transactionId"
                )

                val workoutHistoryStore = workoutHistoryGson.fromJson(
                    workoutHistoryStoreJson,
                    WorkoutHistoryStore::class.java
                )

                processingStep = "processing workout history"
                Log.d(
                    "DataLayerSync",
                    "Processing workout history for transaction: $transactionId"
                )

                val workoutStore = workoutStoreRepository.getWorkoutStore()
                val workout = workoutStore.findWorkoutForHistory(workoutHistoryStore.WorkoutHistory)

                if (workout == null) {
                    throw IllegalStateException("Workout not found for workout history: ${workoutHistoryStore.WorkoutHistory.workoutId}")
                }

                withContext(NonCancellable) {
                    workoutHistoryDao.insertWithVersionCheck(workoutHistoryStore.WorkoutHistory)
                    setHistoryDao.deleteByWorkoutHistoryId(workoutHistoryStore.WorkoutHistory.id)
                    setHistoryDao.insertAllWithVersionCheck(*workoutHistoryStore.SetHistories.toTypedArray())
                    restHistoryDao.deleteByWorkoutHistoryId(workoutHistoryStore.WorkoutHistory.id)
                    restHistoryDao.insertAllWithVersionCheck(*workoutHistoryStore.RestHistories.toTypedArray())

                    if (
                        shouldApplyIncomingWorkoutRecord(
                            incomingHistory = workoutHistoryStore.WorkoutHistory,
                            incomingRecord = workoutHistoryStore.WorkoutRecord,
                            workoutId = workout.id
                        )
                    ) {
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
                            workout.workoutComponents.filterIsInstance<Exercise>() +
                                workout.workoutComponents.filterIsInstance<Superset>()
                                    .flatMap { it.exercises }
                        var workoutComponents = workout.workoutComponents

                        for (exercise in exercises) {
                            val setHistories =
                                setHistoriesByExerciseId[exercise.id]?.sortedBy { it.order }
                                    ?: continue

                            val hasCompletedCalibration = setHistories.any { setHistory ->
                                when (val setData = setHistory.setData) {
                                    is WeightSetData -> setData.subCategory == SetSubCategory.CalibrationSet && setData.calibrationRIR != null
                                    is BodyWeightSetData -> setData.subCategory == SetSubCategory.CalibrationSet && setData.calibrationRIR != null
                                    else -> false
                                }
                            }

                            val updatedExercise = if (hasCompletedCalibration && exercise.requiresLoadCalibration) {
                                exercise.copy(requiresLoadCalibration = false)
                            } else {
                                exercise
                            }

                            if (updatedExercise != exercise) {
                                workoutComponents = updateWorkoutComponentsRecursively(
                                    workoutComponents,
                                    exercise,
                                    updatedExercise
                                )
                            }

                            val sessionMerge =
                                ExerciseSessionReconstruction.mergeCompletedSession(
                                    templateSets = updatedExercise.sets,
                                    rawSetHistoriesForExercise = setHistories,
                                    allRestHistories = workoutHistoryStore.RestHistories,
                                    exerciseId = updatedExercise.id,
                                )
                            workoutComponents =
                                replaceSetsInExerciseRecursively(
                                    workoutComponents,
                                    updatedExercise,
                                    sessionMerge.mergedSets()
                                )
                        }

                        workoutComponents = workoutComponents.map { workoutComponent ->
                            when (workoutComponent) {
                                is Exercise -> workoutComponent.copy(
                                    sets = ensureRestSeparatedBySets(workoutComponent.sets)
                                )
                                is Superset -> workoutComponent.copy(
                                    exercises = workoutComponent.exercises.map { exercise ->
                                        exercise.copy(
                                            sets = ensureRestSeparatedBySets(exercise.sets)
                                        )
                                    }
                                )
                                is Rest -> workoutComponent
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

                    if (workoutHistoryStore.ErrorLogs.isNotEmpty()) {
                        errorLogDao.insertAll(*workoutHistoryStore.ErrorLogs.toTypedArray())
                    }

                    transactionId?.let { tid ->
                        processingStep = "sending sync complete acknowledgment"
                        sendWorkoutHistorySyncComplete(
                            transactionId = tid,
                            workoutHistory = workoutHistoryStore.WorkoutHistory,
                            setCount = workoutHistoryStore.SetHistories.size
                        )
                    }
                }

                val intent = Intent(INTENT_ID).apply {
                    putExtra(UPDATE_WORKOUTS, UPDATE_WORKOUTS)
                }

                intent.apply { setPackage(packageName) }
                sendBroadcast(intent)

                Log.d("WorkoutSync", "Workout history processing completed, transaction: $transactionId")

                updateWorkoutHistorySyncTelemetry(
                    transactionId = transactionId,
                    reason = "processing_complete"
                ) { snapshot ->
                    WorkoutHistorySyncTelemetryPolicy.recordRecoveredAfterRetry(
                        snapshot = snapshot,
                        latestRequestedRetryGeneration = retryGenerationsUsed
                    )
                }
                markTerminalTransaction(transactionId)
                clearActiveWorkoutHistoryTransactionState()

                processingStep = "scheduling workout backup"
                runCatching {
                    BackupCoordinator.onWorkoutStorePersisted(
                        context = this@DataLayerListenerService,
                        trigger = BackupCoordinator.Trigger.WEAR_PERSIST
                    )
                }.onFailure { exception ->
                    Log.e(
                        "DataLayerSync",
                        "Failed to schedule workout store backup after successful workout history sync",
                        exception
                    )
                }
            } catch (exception: Exception) {
                val exceptionClassName = exception.javaClass.simpleName
                val exceptionMessage = exception.message

                val fullErrorMessage = when {
                    !exceptionMessage.isNullOrEmpty() -> {
                        "$exceptionClassName at $processingStep: $exceptionMessage"
                    }

                    else -> {
                        "$exceptionClassName at $processingStep: Unknown error processing workout history"
                    }
                }

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

                transactionId?.let { tid ->
                    try {
                        Log.e(
                            "DataLayerSync",
                            "Sending SYNC_ERROR for transaction: $tid due to workout history processing error"
                        )
                        Log.d(
                            "WorkoutSync",
                            "SYNC_TRACE event=error side=mobile direction=send tx=$tid message=$errorMessage"
                        )
                        val errorPath = DataLayerPaths.buildPath(
                            DataLayerPaths.SYNC_ERROR_PREFIX,
                            tid
                        )
                        val errorDataMapRequest = PutDataMapRequest.create(errorPath)
                        errorDataMapRequest.dataMap.putString("transactionId", tid)
                        errorDataMapRequest.dataMap.putString("errorMessage", errorMessage)
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

                markTerminalTransaction(transactionId)
                clearActiveWorkoutHistoryTransactionState()
            }
        } finally {
            PhoneSyncToWatchSuppressor.exitWearInboundApply()
        }
    }

    private suspend fun sendWorkoutHistorySyncComplete(
        transactionId: String,
        workoutHistory: WorkoutHistory,
        setCount: Int
    ) {
        Log.d(
            "WorkoutSync",
            "SYNC_TRACE event=process_done side=mobile tx=$transactionId historyId=${workoutHistory.id} isDone=${workoutHistory.isDone} sets=$setCount"
        )
        Log.d(
            "WorkoutSync",
            "SYNC_TRACE event=complete side=mobile direction=send tx=$transactionId"
        )
        Log.d("WorkoutSync", "Sent SYNC_COMPLETE for transaction: $transactionId")
        Log.d(
            "DataLayerSync",
            "Preparing to send SYNC_COMPLETE for transaction: $transactionId (workout history processed)"
        )

        val completePath = DataLayerPaths.buildPath(
            DataLayerPaths.SYNC_COMPLETE_PREFIX,
            transactionId
        )
        val completeDataMapRequest = PutDataMapRequest.create(completePath)
        completeDataMapRequest.dataMap.putString("transactionId", transactionId)
        val timestamp = System.currentTimeMillis().toString()
        completeDataMapRequest.dataMap.putString("timestamp", timestamp)

        val completeRequest = completeDataMapRequest.asPutDataRequest().setUrgent()
        Log.d(
            "DataLayerSync",
            "Sending SYNC_COMPLETE for transaction: $transactionId, timestamp: $timestamp"
        )
        Tasks.await(dataClient.putDataItem(completeRequest))
        Log.d(
            "DataLayerSync",
            "Successfully sent SYNC_COMPLETE for transaction: $transactionId (workout history)"
        )
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

    private fun resolveLocalNodeId(): String? {
        localNodeId?.let { return it }
        return runCatching {
            Tasks.await(nodeClient.localNode).id
        }.getOrNull()?.also { resolved ->
            localNodeId = resolved
        }
    }

    private fun isSelfOriginatedEvent(uri: Uri): Boolean {
        val sourceNodeId = uri.host ?: return false
        val ownNodeId = resolveLocalNodeId() ?: return false
        return sourceNodeId == ownNodeId
    }

    override fun onCreate() {
        super.onCreate()
        val db = AppDatabase.getDatabase(this)
        setHistoryDao = db.setHistoryDao()
        restHistoryDao = db.restHistoryDao()
        workoutHistoryDao = db.workoutHistoryDao()
        exerciseInfoDao = db.exerciseInfoDao()
        workoutRecordDao = db.workoutRecordDao()
        exerciseSessionProgressionDao = db.exerciseSessionProgressionDao()
        errorLogDao = db.errorLogDao()
        scope.launch {
            localNodeId = resolveLocalNodeId()
        }
        
        // Detect service restart and handle incomplete syncs
        detectAndHandleServiceRestart()
    }

    private suspend fun shouldApplyIncomingWorkoutRecord(
        incomingHistory: WorkoutHistory,
        incomingRecord: WorkoutRecord?,
        workoutId: UUID
    ): Boolean {
        if (incomingRecord == null) {
            return false
        }

        var existingRecord = workoutRecordDao.getWorkoutRecordByWorkoutId(workoutId) ?: return true
        var existingHistory =
            workoutHistoryDao.getWorkoutHistoryById(existingRecord.workoutHistoryId) ?: return true

        if (existingHistory.isDone) {
            workoutRecordDao.deleteByWorkoutId(workoutId)
            existingRecord = workoutRecordDao.getWorkoutRecordByWorkoutId(workoutId) ?: return true
            existingHistory =
                workoutHistoryDao.getWorkoutHistoryById(existingRecord.workoutHistoryId) ?: return true
        }

        val decision = decideWorkoutRecordIngest(
            incomingHistory = incomingHistory,
            incomingRecord = incomingRecord,
            existingHistory = existingHistory,
            existingRecord = existingRecord
        )
        if (!decision.shouldApplyIncoming) {
            Log.w(
                "WorkoutSync",
                "Ignoring incoming workout record for workoutId=$workoutId " +
                    "incomingRevision=${incomingRecord.activeSessionRevision} " +
                    "existingRevision=${existingRecord.activeSessionRevision} " +
                    "incomingVersion=${incomingHistory.version} existingVersion=${existingHistory.version}"
            )
            return false
        }

        if (decision.shouldPruneExisting && existingRecord.id != incomingRecord.id) {
            workoutRecordDao.deleteById(existingRecord.id)
        }
        return true
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
            clearActiveWorkoutHistoryTransactionState()
            
            // Notify UI that sync was interrupted
            val intent = Intent(INTENT_ID).apply {
                putExtra(UPDATE_WORKOUTS, UPDATE_WORKOUTS)
                setPackage(packageName)
            }
            sendBroadcast(intent)
        }
        
        // Update last service start time
        sharedPreferences.edit().putLong("last_service_start_time", currentTime).apply()
        pruneTerminalTransactions(currentTime)
    }

    private fun handlePhoneLlmOperationRequest(
        path: String,
        dataMap: com.google.android.gms.wearable.DataMap,
    ) {
        val requestId = DataLayerPaths.parseTransactionId(
            path,
            DataLayerPaths.PHONE_LLM_OPERATION_REQUEST_PREFIX
        ) ?: dataMap.getString(PhoneLlmDataMapKeys.REQUEST_ID)

        if (requestId.isNullOrBlank()) {
            Log.w("PhoneLlmOperation", "Received LLM operation request without requestId")
            return
        }

        val requestJson = dataMap.getString(PhoneLlmDataMapKeys.REQUEST_JSON)
        scope.launch(Dispatchers.IO) {
            val result = if (requestJson.isNullOrBlank()) {
                PhoneLlmOperationResult.error(
                    requestId = requestId,
                    operation = DEFAULT_PHONE_LLM_OPERATION,
                    errorMessage = "Missing LLM operation request payload."
                )
            } else {
                try {
                    val parsedRequest = gson.fromJson(
                        requestJson,
                        PhoneLlmOperationRequest::class.java
                    ) ?: error("Invalid LLM operation request payload.")
                    phoneLlmOperationExecutor.execute(parsedRequest.copy(requestId = requestId))
                } catch (exception: CancellationException) {
                    throw exception
                } catch (exception: Exception) {
                    PhoneLlmOperationResult.error(
                        requestId = requestId,
                        operation = DEFAULT_PHONE_LLM_OPERATION,
                        errorMessage = exception.message ?: "Failed to parse LLM operation request."
                    )
                }
            }

            sendPhoneLlmOperationResult(result.copy(requestId = requestId))
        }
    }

    private suspend fun sendPhoneLlmOperationResult(
        result: PhoneLlmOperationResult,
    ) {
        try {
            val resultPath = DataLayerPaths.buildPath(
                DataLayerPaths.PHONE_LLM_OPERATION_RESULT_PREFIX,
                result.requestId
            )
            val resultRequest = PutDataMapRequest.create(resultPath).apply {
                dataMap.putString(PhoneLlmDataMapKeys.REQUEST_ID, result.requestId)
                dataMap.putString(PhoneLlmDataMapKeys.RESULT_JSON, gson.toJson(result))
                dataMap.putString(
                    PhoneLlmDataMapKeys.TIMESTAMP,
                    System.currentTimeMillis().toString()
                )
            }.asPutDataRequest().setUrgent()

            Tasks.await(dataClient.putDataItem(resultRequest))
            Log.d(
                "PhoneLlmOperation",
                "Sent LLM operation result for request: ${result.requestId}, status: ${result.status}"
            )
        } catch (exception: Exception) {
            Log.e(
                "PhoneLlmOperation",
                "Failed to send LLM operation result for request: ${result.requestId}",
                exception
            )
        }
    }

    private fun parseWorkoutSessionHeartbeat(
        dataMap: com.google.android.gms.wearable.DataMap
    ): WorkoutSessionHeartbeat? {
        val workoutId = dataMap.getString(WorkoutSessionHeartbeatKeys.WORKOUT_ID)
            ?.let { runCatching { UUID.fromString(it) }.getOrNull() }
        val workoutHistoryId = dataMap.getString(WorkoutSessionHeartbeatKeys.WORKOUT_HISTORY_ID)
            ?.let { runCatching { UUID.fromString(it) }.getOrNull() }
        val exerciseId = dataMap.getString(WorkoutSessionHeartbeatKeys.EXERCISE_ID)
            ?.let { runCatching { UUID.fromString(it) }.getOrNull() }
        val sessionState = dataMap.getString(WorkoutSessionHeartbeatKeys.SESSION_STATE)
        val setIndex = dataMap.getLong(WorkoutSessionHeartbeatKeys.SET_INDEX, -1L)
        val activeSessionRevision = dataMap.getLong(
            WorkoutSessionHeartbeatKeys.ACTIVE_SESSION_REVISION,
            -1L
        )
        val sentAtEpochMs = dataMap.getLong(WorkoutSessionHeartbeatKeys.SENT_AT_EPOCH_MS, -1L)

        if (
            workoutId == null ||
            workoutHistoryId == null ||
            exerciseId == null ||
            sessionState.isNullOrBlank() ||
            setIndex < 0L ||
            activeSessionRevision < 0L ||
            sentAtEpochMs <= 0L
        ) {
            Log.w(
                "WorkoutSessionHeartbeat",
                "Ignoring malformed heartbeat workoutId=$workoutId workoutHistoryId=$workoutHistoryId " +
                    "exerciseId=$exerciseId sessionState=$sessionState setIndex=$setIndex " +
                    "revision=$activeSessionRevision sentAt=$sentAtEpochMs"
            )
            return null
        }

        return WorkoutSessionHeartbeat(
            workoutId = workoutId,
            workoutHistoryId = workoutHistoryId,
            exerciseId = exerciseId,
            setIndex = setIndex.toUInt(),
            sessionState = sessionState,
            activeSessionRevision = activeSessionRevision.toUInt(),
            sentAtEpochMs = sentAtEpochMs
        )
    }

    private suspend fun applyWorkoutSessionHeartbeat(
        heartbeat: WorkoutSessionHeartbeat,
        packageName: String
    ) {
        val existingRecord = workoutRecordDao.getWorkoutRecordByWorkoutId(heartbeat.workoutId)
        val existingHistory = existingRecord
            ?.workoutHistoryId
            ?.let { workoutHistoryDao.getWorkoutHistoryById(it) }

        val decision = decideWorkoutSessionHeartbeatApply(
            heartbeat = heartbeat,
            existingRecord = existingRecord,
            existingHistory = existingHistory
        )
        if (!decision.shouldApply) {
            Log.d(
                "WorkoutSessionHeartbeat",
                "Ignoring heartbeat reason=${decision.rejectReason} workoutId=${heartbeat.workoutId} " +
                    "historyId=${heartbeat.workoutHistoryId} revision=${heartbeat.activeSessionRevision}"
            )
            return
        }

        val updatedRecord = existingRecord!!.copy(
            exerciseId = heartbeat.exerciseId,
            setIndex = heartbeat.setIndex,
            lastActiveSyncAt = heartbeat.sentAtLocalDateTime(),
            activeSessionRevision = heartbeat.activeSessionRevision,
            lastKnownSessionState = heartbeat.sessionState
        )
        workoutRecordDao.insert(updatedRecord)

        val intent = Intent(INTENT_ID).apply {
            putExtra(UPDATE_WORKOUTS, UPDATE_WORKOUTS)
            setPackage(packageName)
        }
        sendBroadcast(intent)
        Log.d(
            "WorkoutSessionHeartbeat",
            "Applied heartbeat workoutId=${heartbeat.workoutId} historyId=${heartbeat.workoutHistoryId} " +
                "revision=${heartbeat.activeSessionRevision} state=${heartbeat.sessionState}"
        )
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
                if (isSelfOriginatedEvent(uri)) {
                    Log.d("DataLayerSync", "Ignoring self-originated data event: ${uri.path}")
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
                                    "Watch sync complete.",
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
                if (eventType != com.google.android.gms.wearable.DataEvent.TYPE_CHANGED) {
                    return@forEach
                }
                if (isSelfOriginatedEvent(uri)) {
                    Log.d("DataLayerSync", "Ignoring self-originated data event: ${uri.path}")
                    return@forEach
                }
                val path = uri.path ?: return@forEach
                when {
                    DataLayerPaths.matchesPrefix(
                        path,
                        DataLayerPaths.PHONE_LLM_OPERATION_REQUEST_PREFIX
                    ) -> {
                        val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                        handlePhoneLlmOperationRequest(path, dataMap)
                    }

                    path == DataLayerPaths.WORKOUT_SESSION_HEARTBEAT_PATH -> {
                        val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                        val heartbeat = parseWorkoutSessionHeartbeat(dataMap) ?: return@forEach
                        scope.launch(Dispatchers.IO) {
                            runCatching {
                                applyWorkoutSessionHeartbeat(heartbeat, packageName)
                            }.onFailure { exception ->
                                Log.e(
                                    "WorkoutSessionHeartbeat",
                                    "Failed applying heartbeat workoutId=${heartbeat.workoutId} " +
                                        "historyId=${heartbeat.workoutHistoryId}",
                                    exception
                                )
                            }
                        }
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

                        if (finalTransactionId != null) {
                            Log.d(
                                "WorkoutSync",
                                "Received SYNC_REQUEST for transaction: $finalTransactionId"
                            )
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

                                    Tasks.await(dataClient.putDataItem(ackRequest))
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
                    DataLayerPaths.matchesPrefix(path, DataLayerPaths.WORKOUT_HISTORY_DISCARD_PREFIX) -> {
                        val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                        val transactionId = DataLayerPaths.parseTransactionId(
                            path,
                            DataLayerPaths.WORKOUT_HISTORY_DISCARD_PREFIX
                        ) ?: dataMap.getString("transactionId")
                        val workoutIdRaw = dataMap.getString("workoutId")
                        val workoutHistoryIdRaw = dataMap.getString("workoutHistoryId")

                        if (workoutIdRaw.isNullOrBlank() || workoutHistoryIdRaw.isNullOrBlank()) {
                            Log.w(
                                "WorkoutSync",
                                "Discard event missing ids tx=$transactionId workoutId=$workoutIdRaw workoutHistoryId=$workoutHistoryIdRaw"
                            )
                            return@forEach
                        }

                        val workoutId = runCatching { UUID.fromString(workoutIdRaw) }.getOrNull()
                        val workoutHistoryId = runCatching { UUID.fromString(workoutHistoryIdRaw) }.getOrNull()
                        if (workoutId == null || workoutHistoryId == null) {
                            Log.w(
                                "WorkoutSync",
                                "Discard event has invalid UUID tx=$transactionId workoutId=$workoutIdRaw workoutHistoryId=$workoutHistoryIdRaw"
                            )
                            return@forEach
                        }

                        scope.launch(Dispatchers.IO) {
                            runCatching {
                                withContext(NonCancellable) {
                                    setHistoryDao.deleteByWorkoutHistoryId(workoutHistoryId)
                                    workoutRecordDao.deleteByWorkoutId(workoutId)
                                    workoutHistoryDao.deleteById(workoutHistoryId)
                                }
                                val intent = Intent(INTENT_ID).apply {
                                    putExtra(UPDATE_WORKOUTS, UPDATE_WORKOUTS)
                                    setPackage(packageName)
                                }
                                sendBroadcast(intent)
                                Log.d(
                                    "WorkoutSync",
                                    "Applied workout discard tx=$transactionId workoutId=$workoutId workoutHistoryId=$workoutHistoryId"
                                )
                            }.onFailure { exception ->
                                Log.e(
                                    "WorkoutSync",
                                    "Failed applying workout discard tx=$transactionId workoutId=$workoutId workoutHistoryId=$workoutHistoryId",
                                    exception
                                )
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
                            val retryGeneration = if (isRetry) {
                                dataMap.getInt("retryGeneration", 1).coerceAtLeast(1)
                            } else {
                                0
                            }
                            val hasActiveTransaction = WorkoutHistoryInboundStatePolicy
                                .hasActiveTransaction(currentTransactionState)

                            if (
                                WorkoutHistoryInboundStatePolicy.shouldIgnoreTerminalReplay(
                                    isTerminalTransaction(transactionId)
                                )
                            ) {
                                Log.d(
                                    "WorkoutSync",
                                    "Ignoring replayed workout history event for terminal transaction: $transactionId"
                                )
                                return@forEach
                            }

                            if (
                                WorkoutHistoryInboundStatePolicy.shouldIgnoreStaleRetryChunk(
                                    isRetry = isRetry,
                                    retryGeneration = retryGeneration,
                                    latestRequestedRetryGeneration = latestRequestedRetryGeneration
                                )
                            ) {
                                updateWorkoutHistorySyncTelemetry(
                                    transactionId = transactionId,
                                    reason = "stale_retry_ignored"
                                ) { snapshot ->
                                    WorkoutHistorySyncTelemetryPolicy.recordStaleRetryIgnored(snapshot)
                                }
                                Log.d(
                                    "WorkoutSync",
                                    "Ignoring stale retry chunk for transaction: $transactionId, " +
                                        "chunkIndex=$chunkIndex, retryGeneration=$retryGeneration, " +
                                        "latestRequestedRetryGeneration=$latestRequestedRetryGeneration"
                                )
                                return@forEach
                            }

                            // Retry chunks with same transaction ID should not trigger shouldStop
                            val shouldStop = WorkoutHistoryInboundStatePolicy
                                .shouldResetForDifferentActiveTransaction(
                                    currentTransactionId = currentTransactionId,
                                    currentState = currentTransactionState,
                                    incomingTransactionId = transactionId,
                                    isStart = isStart,
                                    hasChunkPayload = workoutHistoryChunk != null,
                                    isRetry = isRetry
                                )

                            Log.d(
                                "DataLayerListenerService",
                                "ignoreUntilStartOrEnd: $ignoreUntilStartOrEnd state=$currentTransactionState active=$hasActiveTransaction hasWorkoutHistoryChunk: ${workoutHistoryChunk != null} isStart: $isStart isLastChunk: $isLastChunk isRetry: $isRetry chunkIndex: $chunkIndex transactionId: $transactionId shouldStop: $shouldStop"
                            )

                            if (!ignoreUntilStartOrEnd && shouldStop && !isRetry) {
                                val intent = Intent(INTENT_ID).apply {
                                    putExtra(UPDATE_WORKOUTS, UPDATE_WORKOUTS)
                                    setPackage(packageName)
                                }

                                sendBroadcast(intent)

                                clearActiveWorkoutHistoryTransactionState()

                                ignoreUntilStartOrEnd = true
                                return@forEach
                            }

                            if (isStart) {
                                if (dataMap.containsKey("chunksCount")) {
                                    expectedChunks = dataMap.getInt("chunksCount", 0)
                                }

                                Log.d(
                                    "WorkoutSync",
                                    "Workout history sync started, transaction: $transactionId, expected chunks: $expectedChunks"
                                )
                                Log.d(
                                    "WorkoutSync",
                                    "SYNC_TRACE event=start side=mobile direction=recv tx=$transactionId expectedChunks=$expectedChunks"
                                )
                                Log.d(
                                    "DataLayerSync",
                                    "Workout history backup started with expected chunks: $expectedChunks, transactionId: $transactionId"
                                )

                                workoutHistoryChunks = mutableMapOf()
                                receivedChunkIndices = mutableSetOf()
                                hasStartedSync = true
                                ignoreUntilStartOrEnd = false
                                latestRequestedRetryGeneration = 0
                                currentTransactionId = transactionId
                                currentTransactionState = WorkoutHistoryInboundState.Receiving
                                cancelPendingWorkoutHistoryProcessing()
                            }

                            if (workoutHistoryChunk != null && (!ignoreUntilStartOrEnd || isRetry)) {
                                // Handle chunk with index
                                if (chunkIndex >= 0) {
                                    val isDuplicateChunk = chunkIndex in receivedChunkIndices
                                    val currentChunks = workoutHistoryChunks.toMutableMap()
                                    currentChunks[chunkIndex] = workoutHistoryChunk
                                    workoutHistoryChunks = currentChunks

                                    val currentIndices = receivedChunkIndices.toMutableSet()
                                    currentIndices.add(chunkIndex)
                                    receivedChunkIndices = currentIndices

                                    Log.d(
                                        "WorkoutSync",
                                        "Received workout history chunk, transaction: $transactionId, chunkIndex: $chunkIndex, total received: ${workoutHistoryChunks.size}, expected: $expectedChunks"
                                    )
                                    Log.d(
                                        "DataLayerSync",
                                        "Received workout history chunk at index $chunkIndex. Total chunks: ${workoutHistoryChunks.size}, expected: $expectedChunks, isRetry: $isRetry"
                                    )
                                    if (isDuplicateChunk) {
                                        Log.d(
                                            "DataLayerSync",
                                            "Received duplicate workout history chunk for transaction: $transactionId, chunkIndex: $chunkIndex"
                                        )
                                    }
                                    Log.d(
                                        "WorkoutSync",
                                        "SYNC_TRACE event=chunk side=mobile direction=recv tx=$transactionId " +
                                            "index=$chunkIndex isLast=$isLastChunk isRetry=$isRetry " +
                                            "retryGeneration=$retryGeneration received=${workoutHistoryChunks.size} expected=$expectedChunks"
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
                                    Log.d(
                                        "WorkoutSync",
                                        "SYNC_TRACE event=chunk side=mobile direction=recv tx=$transactionId " +
                                            "index=$nextIndex isLast=$isLastChunk isRetry=$isRetry " +
                                            "retryGeneration=$retryGeneration received=${workoutHistoryChunks.size} expected=$expectedChunks"
                                    )
                                }
                                val hasAllChunks = WorkoutHistoryChunkProcessingPolicy
                                    .shouldProcessImmediately(
                                        receivedChunks = receivedChunkIndices.size,
                                        expectedChunks = expectedChunks
                                    )
                                when {
                                    hasAllChunks -> {
                                        Log.d(
                                            "WorkoutSync",
                                            "All workout history chunks received for transaction: $transactionId, processing now"
                                        )
                                        launchWorkoutHistoryProcessing(transactionId)
                                    }

                                    WorkoutHistoryChunkProcessingPolicy.shouldScheduleSettleWindow(
                                        receivedChunks = receivedChunkIndices.size,
                                        expectedChunks = expectedChunks,
                                        sawTerminalChunk = isLastChunk || isLastRetryChunk,
                                        alreadyWaitingForTrailingChunks = pendingWorkoutHistoryProcessingJob != null
                                    ) -> {
                                        Log.d(
                                            "WorkoutSync",
                                            "Received terminal or trailing chunk for transaction: $transactionId, waiting for settle window before validation"
                                        )
                                        Log.d(
                                            "DataLayerSync",
                                            "Chunk settle window armed (isLastChunk: $isLastChunk, isLastRetryChunk: $isLastRetryChunk). Total chunks received: ${workoutHistoryChunks.size}, expected: $expectedChunks"
                                        )
                                        scheduleWorkoutHistoryProcessing(transactionId)
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
                            val launchIntent = context.packageManager
                                .getLaunchIntentForPackage(context.packageName)
                                ?.apply {
                                    putExtra(PAGE, valueToPass)
                                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                                    addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP)
                                    addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP)
                                }
                                ?: Intent(context, MainActivity::class.java).apply {
                                    putExtra(PAGE, valueToPass)
                                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                                    addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP)
                                    addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP)
                                }
                            withContext(Dispatchers.Main) {
                                startActivity(launchIntent)
                            }
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

    private fun buildMissingChunksErrorMessage(
        expectedChunks: Int,
        receivedChunks: Int,
        missingIndices: List<Int>,
        retryGeneration: Int
    ): String {
        return "MISSING_CHUNKS: Retry generation: $retryGeneration. " +
            "Expected $expectedChunks chunks, received $receivedChunks. Missing indices: $missingIndices"
    }

    companion object {
        private const val WORKOUT_HISTORY_CHUNK_SETTLE_MS = 1500L
        private const val TERMINAL_TRANSACTION_TTL_MS = 10 * 60 * 1000L
        private const val OPEN_PAGE_PATH = "/openPagePath" // Define your new URI path here
        const val CLEAR_ERROR_LOGS_PATH = "/clearErrorLogs"
        const val ERROR_LOGS_SYNC_PATH = "/errorLogsSync"
        const val INTENT_ID = "com.gabstra.myworkoutassistant.WORKOUT_STORE"
        const val UPDATE_WORKOUTS = "update_workouts"
        const val ERROR_LOGS_SYNCED = "error_logs_synced"
        const val PAGE = "page"
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
