package com.gabstra.myworkoutassistant.sync

import android.content.Context
import android.util.Log
import androidx.core.content.edit
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.datalayer.DataLayerPaths
import com.gabstra.myworkoutassistant.shared.datalayer.MotionCaptureSyncMappings
import com.gabstra.myworkoutassistant.shared.datalayer.SensorSessionPayloadCodec
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureExportMetadata
import com.google.android.gms.tasks.Tasks
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.DataMap
import com.google.android.gms.wearable.PutDataMapRequest
import com.google.android.gms.wearable.Wearable
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.util.UUID

/**
 * Phone-side receiver for the `/sensorSession/...` Data Layer channel. Mirrors the workout-history
 * inbound flow: a SharedPreferences-persisted state machine, missing-chunk detection with retry
 * generations, and terminal-transaction dedupe. Chunk payloads are staged on disk (sessions are
 * ~20 MB gzipped, too large for SharedPreferences).
 *
 * On completion the payload is reconstructed into the watch's storage layout:
 * `motion_capture_session`/`motion_capture_segment` rows upserted from `metadata.json` plus the
 * chunk files and `events.csv` moved into `filesDir/motion_capture/sessions/<sessionDirectoryName>/`.
 */
class SensorSessionInboundReceiver(
    private val context: Context,
    private val dataClient: DataClient,
    private val scope: CoroutineScope
) {
    private val gson = Gson()
    private val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    private var currentState: SensorSessionInboundState
        get() {
            val stored = prefs.getString(STATE_KEY, null)
            return runCatching {
                if (stored.isNullOrBlank()) {
                    SensorSessionInboundState.Idle
                } else {
                    enumValueOf<SensorSessionInboundState>(stored)
                }
            }.getOrElse {
                SensorSessionInboundState.Idle
            }
        }
        set(value) {
            prefs.edit { putString(STATE_KEY, value.name) }
        }

    private var currentTransactionId: String?
        get() = prefs.getString(CURRENT_TX_KEY, null)
        set(value) {
            prefs.edit {
                if (value == null) {
                    remove(CURRENT_TX_KEY)
                } else {
                    putString(CURRENT_TX_KEY, value)
                }
            }
        }

    private var expectedChunks: Int
        get() = prefs.getInt(EXPECTED_CHUNKS_KEY, 0)
        set(value) {
            prefs.edit { putInt(EXPECTED_CHUNKS_KEY, value) }
        }

    private var latestRequestedRetryGeneration: Int
        get() = prefs.getInt(LATEST_RETRY_GENERATION_KEY, 0)
        set(value) {
            prefs.edit { putInt(LATEST_RETRY_GENERATION_KEY, value) }
        }

    private var lastActivityAt: Long
        get() = prefs.getLong(LAST_ACTIVITY_KEY, 0L)
        set(value) {
            prefs.edit { putLong(LAST_ACTIVITY_KEY, value) }
        }

    private var terminalTransactionTimestamps: MutableMap<String, Long>
        get() {
            val jsonString = prefs.getString(TERMINAL_TRANSACTIONS_KEY, null) ?: return mutableMapOf()
            return runCatching {
                val typeToken = object : TypeToken<Map<String, Long>>() {}.type
                gson.fromJson<Map<String, Long>>(jsonString, typeToken)?.toMutableMap()
                    ?: mutableMapOf()
            }.getOrElse {
                prefs.edit { remove(TERMINAL_TRANSACTIONS_KEY) }
                mutableMapOf()
            }
        }
        set(value) {
            prefs.edit {
                if (value.isEmpty()) {
                    remove(TERMINAL_TRANSACTIONS_KEY)
                } else {
                    putString(TERMINAL_TRANSACTIONS_KEY, gson.toJson(value))
                }
            }
        }

    private var settleWindowJob: Job? = null
    private var processingJob: Job? = null

    // region Event entry points

    fun handleStart(path: String, dataMap: DataMap) {
        val transactionId = DataLayerPaths.parseTransactionId(
            path,
            DataLayerPaths.SENSOR_SESSION_START_PREFIX
        ) ?: dataMap.getString("transactionId")
        if (transactionId == null) {
            Log.w(TAG, "Sensor session start without transactionId")
            return
        }
        if (isTerminalTransaction(transactionId)) {
            Log.d(TAG, "Ignoring replayed sensor session start for terminal transaction: $transactionId")
            return
        }
        touchActivity()
        if (isStale()) {
            resetActiveTransactionState()
        }

        val expected = dataMap.getInt("chunksCount", 0)
        if (currentTransactionId != null && currentTransactionId != transactionId) {
            Log.w(
                TAG,
                "Resetting active sensor session transaction $currentTransactionId for new transaction: $transactionId"
            )
            resetActiveTransactionState()
        }

        // A late start item after some chunks: keep the already-received chunks and record the
        // expected count so missing-chunk validation works either way.
        expectedChunks = expected
        currentTransactionId = transactionId
        latestRequestedRetryGeneration = 0
        currentState = SensorSessionInboundState.Receiving
        Log.d(
            TAG,
            "SYNC_TRACE event=start side=mobile direction=recv channel=sensorSession tx=$transactionId expectedChunks=$expected"
        )

        maybeLaunchProcessing(transactionId, sawTerminalChunk = false)
    }

    fun handleChunk(path: String, dataMap: DataMap) {
        val transactionId = DataLayerPaths.parseTransactionId(
            path,
            DataLayerPaths.SENSOR_SESSION_CHUNK_PREFIX
        ) ?: dataMap.getString("transactionId")
        val chunk = dataMap.getByteArray("chunk") ?: return
        val chunkIndex = DataLayerPaths.parseChunkIndex(
            path,
            DataLayerPaths.SENSOR_SESSION_CHUNK_PREFIX
        ) ?: dataMap.getInt("chunkIndex", -1)
        if (transactionId == null || chunkIndex < 0) {
            Log.w(TAG, "Sensor session chunk without transaction or index")
            return
        }
        if (isTerminalTransaction(transactionId)) {
            Log.d(TAG, "Ignoring replayed sensor session chunk for terminal transaction: $transactionId")
            return
        }
        touchActivity()
        if (isStale()) {
            resetActiveTransactionState()
        }

        val isRetry = dataMap.getBoolean("isRetry", false)
        val retryGeneration = if (isRetry) dataMap.getInt("retryGeneration", 1).coerceAtLeast(1) else 0
        if (isRetry && latestRequestedRetryGeneration > 0 && retryGeneration < latestRequestedRetryGeneration) {
            Log.d(
                TAG,
                "Ignoring stale retry chunk tx=$transactionId index=$chunkIndex " +
                    "retryGeneration=$retryGeneration latestRequested=$latestRequestedRetryGeneration"
            )
            return
        }

        if (currentTransactionId == null) {
            // Start item has not arrived yet; adopt the transaction so chunks are not dropped.
            currentTransactionId = transactionId
            currentState = SensorSessionInboundState.Receiving
        } else if (currentTransactionId != transactionId) {
            Log.w(
                TAG,
                "Ignoring sensor session chunk for mismatched transaction: $transactionId (active: $currentTransactionId)"
            )
            return
        }

        val isLastChunk = dataMap.getBoolean("isLastChunk", false)
        val isLastRetryChunk = dataMap.getBoolean("isLastRetryChunk", false)

        chunkFile(transactionId, chunkIndex).let { target ->
            target.parentFile?.mkdirs()
            target.writeBytes(chunk)
        }
        Log.d(
            TAG,
            "SYNC_TRACE event=chunk side=mobile direction=recv channel=sensorSession tx=$transactionId " +
                "index=$chunkIndex isRetry=$isRetry received=${receivedChunkIndices(transactionId).size} expected=$expectedChunks"
        )

        maybeLaunchProcessing(
            transactionId = transactionId,
            sawTerminalChunk = isLastChunk || isLastRetryChunk
        )
    }

    fun handleDiscard(path: String, dataMap: DataMap) {
        val transactionId = DataLayerPaths.parseTransactionId(
            path,
            DataLayerPaths.SENSOR_SESSION_DISCARD_PREFIX
        ) ?: dataMap.getString("transactionId")
        val sessionId = dataMap.getString("sessionId")
            ?.let { runCatching { UUID.fromString(it) }.getOrNull() }
        if (sessionId == null) {
            Log.w(TAG, "Sensor session discard without a valid sessionId tx=$transactionId")
            return
        }

        scope.launch(Dispatchers.IO) {
            runCatching {
                withContext(NonCancellable) {
                    val db = AppDatabase.getDatabase(context)
                    val session = db.motionCaptureSessionDao().getById(sessionId)
                    db.motionCaptureSyncDao().deleteSegmentsBySessionId(sessionId)
                    db.motionCaptureSyncDao().deleteSessionById(sessionId)
                    session?.sessionDirectoryName?.let { deleteSessionDirectory(it) }
                }
                if (!transactionId.isNullOrBlank()) {
                    sendSyncComplete(transactionId, "sensor session discard")
                }
                Log.d(TAG, "Applied sensor session discard tx=$transactionId sessionId=$sessionId")
            }.onFailure { exception ->
                Log.e(TAG, "Failed applying sensor session discard sessionId=$sessionId", exception)
            }
        }
    }

    fun shutdown() {
        settleWindowJob?.cancel()
        processingJob?.cancel()
    }

    // endregion

    // region Processing

    private fun maybeLaunchProcessing(transactionId: String, sawTerminalChunk: Boolean) {
        val receivedCount = receivedChunkIndices(transactionId).size
        if (processingJob?.isActive == true) {
            return
        }
        if (expectedChunks > 0 && receivedCount >= expectedChunks) {
            launchProcessing(transactionId)
        } else if (sawTerminalChunk && settleWindowJob?.isActive != true) {
            settleWindowJob = scope.launch(Dispatchers.IO) {
                delay(CHUNK_SETTLE_MS)
                if (processingJob?.isActive != true) {
                    launchProcessing(transactionId)
                }
            }
        }
    }

    private fun launchProcessing(transactionId: String) {
        settleWindowJob?.cancel()
        settleWindowJob = null
        currentState = SensorSessionInboundState.Processing
        processingJob = scope.launch(Dispatchers.IO) {
            processReceivedPayload(transactionId)
        }
    }

    private suspend fun processReceivedPayload(transactionId: String) {
        try {
            val received = receivedChunkIndices(transactionId)
            val missing = (0 until expectedChunks).filterNot { it in received }
            if (expectedChunks <= 0) {
                sendSyncError(transactionId, "MISSING_START: expected chunk count is unknown")
                resetActiveTransactionState()
                return
            }
            if (missing.isNotEmpty()) {
                val retryGeneration = latestRequestedRetryGeneration + 1
                latestRequestedRetryGeneration = retryGeneration
                currentState = SensorSessionInboundState.Receiving
                val errorMessage = SensorSessionPayloadCodec.buildMissingChunksErrorMessage(
                    expectedChunks = expectedChunks,
                    receivedChunks = received.size,
                    missingIndices = missing,
                    retryGeneration = retryGeneration
                )
                Log.e(
                    TAG,
                    "Missing sensor session chunks tx=$transactionId missing=$missing retryGeneration=$retryGeneration"
                )
                sendSyncError(transactionId, errorMessage)
                return
            }

            val payloadBytes = withContext(NonCancellable + Dispatchers.IO) {
                val chunks = (0 until expectedChunks).map { index ->
                    chunkFile(transactionId, index).readBytes()
                }
                SensorSessionPayloadCodec.gunzip(SensorSessionPayloadCodec.combineChunks(chunks))
            }
            applyPayload(transactionId, payloadBytes)

            markTerminalTransaction(transactionId)
            resetActiveTransactionState()
            sendSyncComplete(transactionId, "sensor session")
            Log.d(TAG, "SYNC_TRACE event=complete side=mobile direction=recv channel=sensorSession tx=$transactionId")
        } catch (exception: Exception) {
            Log.e(TAG, "Failed to process sensor session payload tx=$transactionId", exception)
            runCatching { sendSyncError(transactionId, exception.message ?: "Unknown sensor session error") }
            resetActiveTransactionState()
        }
    }

    /** Parses `metadata.json`, upserts the Room rows and materializes the session directory. */
    private suspend fun applyPayload(transactionId: String, payloadBytes: ByteArray) {
        val payloadDirectory = payloadDirectory(transactionId)
        withContext(NonCancellable + Dispatchers.IO) {
            payloadDirectory.deleteRecursively()
            SensorSessionPayloadCodec.unzip(payloadBytes, payloadDirectory)
        }

        val metadataFile = File(payloadDirectory, SensorSessionPayloadCodec.METADATA_FILE_NAME)
        val metadata = gson.fromJson(metadataFile.readText(), MotionCaptureExportMetadata::class.java)
            ?: throw IllegalStateException("Sensor session metadata.json was empty (tx=$transactionId)")
        val sessionDirectory = resolveSessionDirectory(metadata.session.sessionDirectoryName)

        withContext(NonCancellable + Dispatchers.IO) {
            val db = AppDatabase.getDatabase(context)
            db.motionCaptureSessionDao().insert(MotionCaptureSyncMappings.sessionRecordToEntity(metadata.session))
            metadata.coarseReviewedSegments.forEach { segment ->
                db.motionCaptureSegmentDao().insert(MotionCaptureSyncMappings.segmentRecordToEntity(segment))
            }
            sessionDirectory.mkdirs()
            val referencedFiles = metadata.exportedChunkFiles + listOf(metadata.eventsFile)
            referencedFiles.forEach { fileName ->
                File(payloadDirectory, fileName).takeIf { it.isFile }?.copyTo(
                    target = File(sessionDirectory, fileName),
                    overwrite = true
                ) ?: throw IllegalStateException("Referenced file missing from payload: $fileName")
            }
        }
        payloadDirectory.deleteRecursively()
        Log.d(
            TAG,
            "Applied sensor session payload tx=$transactionId sessionId=${metadata.session.id} " +
                "segments=${metadata.coarseReviewedSegments.size} files=${metadata.exportedChunkFiles.size + 1}"
        )
    }

    // endregion

    // region State helpers

    private fun receivedChunkIndices(transactionId: String): Set<Int> {
        return transferDirectory(transactionId)
            .listFiles { file -> file.isFile && file.name.startsWith(CHUNK_FILE_PREFIX) }
            .orEmpty()
            .mapNotNull { file -> file.name.removePrefix(CHUNK_FILE_PREFIX).toIntOrNull() }
            .toSet()
    }

    private fun chunkFile(transactionId: String, index: Int): File =
        File(transferDirectory(transactionId), "$CHUNK_FILE_PREFIX$index")

    private fun transferDirectory(transactionId: String): File =
        File(context.filesDir, "$TRANSFER_ROOT/$transactionId")

    private fun payloadDirectory(transactionId: String): File =
        File(transferDirectory(transactionId), PAYLOAD_DIRECTORY_NAME)

    private fun resolveSessionDirectory(sessionDirectoryName: String): File {
        require(sessionDirectoryName.isNotBlank()) { "Session directory name is blank" }
        require(!sessionDirectoryName.contains(File.separatorChar) && !sessionDirectoryName.contains('/')) {
            "Unexpected session directory name: $sessionDirectoryName"
        }
        return File(File(context.filesDir, SESSIONS_ROOT), sessionDirectoryName)
    }

    private fun deleteSessionDirectory(sessionDirectoryName: String) {
        val sessionDirectory = resolveSessionDirectory(sessionDirectoryName)
        if (sessionDirectory.exists()) {
            sessionDirectory.deleteRecursively()
        }
    }

    private fun resetActiveTransactionState(clearTerminalCandidate: Boolean = true) {
        val transactionId = currentTransactionId
        if (transactionId != null && clearTerminalCandidate) {
            transferDirectory(transactionId).deleteRecursively()
        }
        currentTransactionId = null
        expectedChunks = 0
        latestRequestedRetryGeneration = 0
        currentState = SensorSessionInboundState.Idle
    }

    private fun touchActivity() {
        lastActivityAt = System.currentTimeMillis()
    }

    private fun isStale(): Boolean {
        val lastActivity = lastActivityAt
        return currentState != SensorSessionInboundState.Idle &&
            lastActivity > 0L &&
            System.currentTimeMillis() - lastActivity > STALE_TRANSACTION_TTL_MS
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

    private fun markTerminalTransaction(transactionId: String) {
        if (transactionId.isBlank()) return
        pruneTerminalTransactions()
        val updated = terminalTransactionTimestamps
        updated[transactionId] = System.currentTimeMillis()
        terminalTransactionTimestamps = updated
    }

    // endregion

    // region Handshake senders

    private suspend fun sendSyncComplete(transactionId: String, reason: String) {
        val completePath = DataLayerPaths.buildPath(
            DataLayerPaths.SYNC_COMPLETE_PREFIX,
            transactionId
        )
        val request = PutDataMapRequest.create(completePath).apply {
            dataMap.putString("transactionId", transactionId)
            dataMap.putString("timestamp", System.currentTimeMillis().toString())
        }.asPutDataRequest().setUrgent()
        Tasks.await(dataClient.putDataItem(request))
        Log.d(TAG, "Sent SYNC_COMPLETE for sensor session transaction: $transactionId ($reason)")
    }

    private suspend fun sendSyncError(transactionId: String, errorMessage: String) {
        val errorPath = DataLayerPaths.buildPath(
            DataLayerPaths.SYNC_ERROR_PREFIX,
            transactionId
        )
        val request = PutDataMapRequest.create(errorPath).apply {
            dataMap.putString("transactionId", transactionId)
            dataMap.putString("errorMessage", errorMessage)
            dataMap.putInt("retryGeneration", latestRequestedRetryGeneration)
            dataMap.putString("timestamp", System.currentTimeMillis().toString())
        }.asPutDataRequest().setUrgent()
        Tasks.await(dataClient.putDataItem(request))
        Log.d(TAG, "Sent SYNC_ERROR for sensor session transaction: $transactionId message=$errorMessage")
    }

    // endregion

    private enum class SensorSessionInboundState {
        Idle,
        Receiving,
        Processing
    }

    companion object {
        private const val TAG = "SensorSessionSync"
        private const val PREFS_NAME = "sensor_session_sync_state"
        private const val STATE_KEY = "state"
        private const val CURRENT_TX_KEY = "current_transaction_id"
        private const val EXPECTED_CHUNKS_KEY = "expected_chunks"
        private const val LATEST_RETRY_GENERATION_KEY = "latest_requested_retry_generation"
        private const val LAST_ACTIVITY_KEY = "last_activity_at"
        private const val TERMINAL_TRANSACTIONS_KEY = "terminal_transactions"
        private const val TRANSFER_ROOT = "sensor_session_sync"
        private const val PAYLOAD_DIRECTORY_NAME = "payload"
        private const val CHUNK_FILE_PREFIX = "chunk_"
        private const val SESSIONS_ROOT = "motion_capture/sessions"
        private const val CHUNK_SETTLE_MS = 1500L
        private const val TERMINAL_TRANSACTION_TTL_MS = 10 * 60 * 1000L
        private const val STALE_TRANSACTION_TTL_MS = 30 * 60 * 1000L
    }
}
