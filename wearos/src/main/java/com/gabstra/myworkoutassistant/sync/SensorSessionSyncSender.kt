package com.gabstra.myworkoutassistant.sync

import android.content.Context
import android.net.Uri
import android.util.Log
import com.gabstra.myworkoutassistant.DataLayerListenerService
import com.gabstra.myworkoutassistant.data.SyncHandshakeManager
import com.gabstra.myworkoutassistant.data.WorkoutHistoryRetryProtocol
import com.gabstra.myworkoutassistant.data.checkConnection
import com.gabstra.myworkoutassistant.data.sendSyncRequest
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.datalayer.DataLayerPaths
import com.gabstra.myworkoutassistant.shared.datalayer.MotionCaptureSyncMappings
import com.gabstra.myworkoutassistant.shared.datalayer.SensorSessionPayloadCodec
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureExportService
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSegmentRecord
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSessionRecord
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSessionStatus
import com.google.android.gms.tasks.Tasks
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.PutDataMapRequest
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.selects.select
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import java.io.File
import java.util.UUID

internal data class SensorSessionSyncResult(
    val attemptedSessionIds: Set<UUID>,
    val failedSessionIds: Set<UUID>
)

internal data class BuiltSensorSessionPayload(
    val chunks: List<ByteArray>,
    val payloadBytes: Int
)

/**
 * Builds the transfer payload for one captured sensor session: a self-contained
 * `MotionCaptureExportService` export directory, zipped and then gzipped.
 */
internal object SensorSessionPayloadBuilder {
    private const val TAG = "SensorSessionSync"
    private const val SESSIONS_ROOT = "motion_capture/sessions"
    private const val TEMP_EXPORT_ROOT = "motion_capture/sync_exports"
    private val exportService = MotionCaptureExportService()

    suspend fun build(
        context: Context,
        session: MotionCaptureSessionRecord,
        segments: List<MotionCaptureSegmentRecord>
    ): BuiltSensorSessionPayload = withContext(Dispatchers.IO) {
        val sessionDirectory = File(File(context.filesDir, SESSIONS_ROOT), session.sessionDirectoryName)
        require(sessionDirectory.isDirectory) {
            "Session directory does not exist: ${sessionDirectory.absolutePath}"
        }
        verifyReferencedChunkFilesExist(sessionDirectory, segments)

        val tempExportRoot = File(context.filesDir, TEMP_EXPORT_ROOT)
        tempExportRoot.deleteRecursively()
        try {
            val exportDirectory = exportService.export(
                session = session,
                segments = segments,
                sessionDirectory = sessionDirectory,
                exportRootDirectory = tempExportRoot
            )
            val payload = SensorSessionPayloadCodec.gzip(
                SensorSessionPayloadCodec.zipDirectory(exportDirectory)
            )
            BuiltSensorSessionPayload(
                chunks = SensorSessionPayloadCodec.chunkPayload(payload),
                payloadBytes = payload.size
            )
        } finally {
            tempExportRoot.deleteRecursively()
        }
    }

    /**
     * Guards against a partially compressed session directory (the session row is marked COMPLETED
     * before its chunks are gzipped): a missing referenced file fails the build so the caller can
     * retry after compression has settled.
     */
    private fun verifyReferencedChunkFilesExist(
        sessionDirectory: File,
        segments: List<MotionCaptureSegmentRecord>
    ) {
        val missing = segments
            .flatMap { it.chunkFileNames }
            .distinct()
            .filterNot { File(sessionDirectory, it).isFile }
        require(missing.isEmpty()) {
            "Session directory ${sessionDirectory.name} is missing referenced chunk files: $missing"
        }
    }
}

/**
 * Sends captured sensor sessions to the phone over the Data Layer, mirroring the workout-history
 * channel: `/sync/request` handshake, transaction-scoped start item, chunk items and completion
 * wait with missing-chunk retries. Only one payload is on the wire at a time.
 */
internal object SensorSessionSyncSender {
    private const val TAG = "SensorSessionSyncSender"
    private const val LOG_TAG = "SensorSessionSync"
    private const val MAX_RETRY_ATTEMPTS = 5

    suspend fun send(
        context: Context,
        dataClient: DataClient,
        sessionIds: Set<UUID>
    ): SensorSessionSyncResult {
        if (sessionIds.isEmpty()) {
            return SensorSessionSyncResult(emptySet(), emptySet())
        }

        val db = AppDatabase.getDatabase(context)
        val attemptedIds = linkedSetOf<UUID>()
        val failedIds = linkedSetOf<UUID>()

        for (sessionId in sessionIds) {
            val sessionEntity = db.motionCaptureSessionDao().getById(sessionId) ?: continue
            if (sessionEntity.status != MotionCaptureSessionStatus.COMPLETED.name) {
                Log.d(TAG, "sessionId=$sessionId skipped because status=${sessionEntity.status}")
                continue
            }
            attemptedIds += sessionId
            try {
                val session = MotionCaptureSyncMappings.sessionEntityToRecord(sessionEntity)
                val segments = db.motionCaptureSegmentDao().getBySessionId(sessionId)
                    .map(MotionCaptureSyncMappings::segmentEntityToRecord)
                val payload = SensorSessionPayloadBuilder.build(context, session, segments)

                val success = SensorSessionTransferCoordinator.sendMutex.withLock {
                    sendPayload(context, dataClient, sessionId, payload)
                }
                if (success) {
                    SensorSessionSyncedIdTracker.markSynced(context, sessionId)
                } else {
                    failedIds += sessionId
                }
            } catch (exception: Exception) {
                failedIds += sessionId
                Log.e(TAG, "sessionId=$sessionId failed during sensor session sync", exception)
            }
        }

        return SensorSessionSyncResult(
            attemptedSessionIds = attemptedIds,
            failedSessionIds = failedIds
        )
    }

    private suspend fun sendPayload(
        context: Context,
        dataClient: DataClient,
        sessionId: UUID,
        payload: BuiltSensorSessionPayload
    ): Boolean {
        val transactionId = UUID.randomUUID().toString()
        try {
            cleanupAbandonedSensorSessionDataItems(dataClient)

            val hasConnection = checkConnection(context)
            if (!hasConnection) {
                Log.d(LOG_TAG, "Skipping sensor session sync - phone not connected (tx=$transactionId)")
                return false
            }

            val handshakeSuccess = sendSyncRequest(dataClient, transactionId, context)
            if (!handshakeSuccess) {
                Log.w(
                    LOG_TAG,
                    "Handshake failed (no ACK) for transaction: $transactionId - proceeding with best-effort send"
                )
            }

            val completionWaiter = SyncHandshakeManager.registerCompletionWaiter(transactionId)
            val errorWaiter = SyncHandshakeManager.registerErrorWaiter(transactionId)

            Log.d(
                LOG_TAG,
                "SYNC_TRACE event=start side=wear direction=send channel=sensorSession tx=$transactionId " +
                    "sessionId=$sessionId chunks=${payload.chunks.size} bytes=${payload.payloadBytes}"
            )

            val startPath = DataLayerPaths.buildPath(
                DataLayerPaths.SENSOR_SESSION_START_PREFIX,
                transactionId
            )
            val startRequest = PutDataMapRequest.create(startPath).apply {
                dataMap.putBoolean("isStart", true)
                dataMap.putInt("chunksCount", payload.chunks.size)
                dataMap.putString("sessionId", sessionId.toString())
                dataMap.putString("timestamp", System.currentTimeMillis().toString())
                dataMap.putString("transactionId", transactionId)
            }.asPutDataRequest().setUrgent()
            Tasks.await(dataClient.putDataItem(startRequest))

            sendSensorSessionChunks(
                dataClient = dataClient,
                transactionId = transactionId,
                chunks = payload.chunks,
                chunkIndices = payload.chunks.indices.toList(),
                isRetry = false,
                retryGeneration = 0
            )

            val completionTimeout =
                DataLayerListenerService.calculateCompletionTimeout(payload.chunks.size)
            return awaitCompletion(
                dataClient = dataClient,
                transactionId = transactionId,
                chunks = payload.chunks,
                completionTimeoutMs = completionTimeout,
                completionWaiter = completionWaiter,
                errorWaiter = errorWaiter
            )
        } catch (exception: Exception) {
            SyncHandshakeManager.cleanup(transactionId)
            Log.e(LOG_TAG, "Error sending sensor session payload tx=$transactionId", exception)
            return false
        } finally {
            cleanupSensorSessionTransactionDataItems(dataClient, transactionId)
        }
    }

    private suspend fun sendSensorSessionChunks(
        dataClient: DataClient,
        transactionId: String,
        chunks: List<ByteArray>,
        chunkIndices: List<Int>,
        isRetry: Boolean,
        retryGeneration: Int
    ) {
        chunkIndices.forEachIndexed { position, chunkIndex ->
            if (chunkIndex < 0 || chunkIndex >= chunks.size) {
                Log.e(TAG, "Invalid chunk index in send: $chunkIndex (total chunks: ${chunks.size})")
                return@forEachIndexed
            }
            val isLast = position == chunkIndices.size - 1
            val chunkPath = DataLayerPaths.buildPath(
                DataLayerPaths.SENSOR_SESSION_CHUNK_PREFIX,
                transactionId,
                chunkIndex
            )
            val request = PutDataMapRequest.create(chunkPath).apply {
                dataMap.putByteArray("chunk", chunks[chunkIndex])
                dataMap.putInt("chunkIndex", chunkIndex)
                if (isRetry) {
                    dataMap.putBoolean("isRetry", true)
                    dataMap.putInt("retryGeneration", retryGeneration)
                }
                if (isLast) {
                    dataMap.putBoolean(if (isRetry) "isLastRetryChunk" else "isLastChunk", true)
                }
                dataMap.putString("timestamp", System.currentTimeMillis().toString())
                dataMap.putString("transactionId", transactionId)
            }.asPutDataRequest()
            Tasks.await(dataClient.putDataItem(request))

            Log.d(
                LOG_TAG,
                "SYNC_TRACE event=chunk side=wear direction=send channel=sensorSession " +
                    "tx=$transactionId index=$chunkIndex isRetry=$isRetry"
            )
            // Retries pace re-sent chunks so the receiver can batch them; initial non-urgent
            // chunks are written back-to-back and the transport batches them on its own.
            if (isRetry && !isLast) {
                delay(500)
            }
        }
    }

    private suspend fun awaitCompletion(
        dataClient: DataClient,
        transactionId: String,
        chunks: List<ByteArray>,
        completionTimeoutMs: Long,
        completionWaiter: CompletableDeferred<Unit>,
        errorWaiter: CompletableDeferred<String>
    ): Boolean {
        var currentCompletionWaiter = completionWaiter
        var currentErrorWaiter = errorWaiter
        var retryAttempt = 0

        while (retryAttempt <= MAX_RETRY_ATTEMPTS) {
            val result = withTimeoutOrNull(completionTimeoutMs) {
                select<Pair<Boolean, String?>> {
                    currentCompletionWaiter.onAwait.invoke { Pair(true, null) }
                    currentErrorWaiter.onAwait.invoke { errorMessage -> Pair(false, errorMessage) }
                }
            }

            when {
                result == null -> {
                    Log.e(
                        LOG_TAG,
                        "Completion timeout for sensor session transaction: $transactionId (attempt $retryAttempt)"
                    )
                    if (retryAttempt < MAX_RETRY_ATTEMPTS) {
                        val backoffMs = 500L * (1 shl retryAttempt)
                        delay(backoffMs + (0..200).random().toLong())
                        retryAttempt++
                        currentCompletionWaiter = SyncHandshakeManager.registerCompletionWaiter(transactionId)
                        currentErrorWaiter = SyncHandshakeManager.registerErrorWaiter(transactionId)
                        continue
                    }
                    SyncHandshakeManager.cleanup(transactionId)
                    return false
                }
                result.first -> {
                    Log.d(LOG_TAG, "Sensor session sync completed for transaction: $transactionId")
                    SyncHandshakeManager.cleanup(transactionId)
                    return true
                }
                else -> {
                    val errorMessage = result.second ?: "Unknown error"
                    Log.e(LOG_TAG, "Sync error for sensor session transaction: $transactionId, error: $errorMessage")
                    if (errorMessage.startsWith("MISSING_CHUNKS:") && retryAttempt < MAX_RETRY_ATTEMPTS) {
                        val missingChunksError =
                            WorkoutHistoryRetryProtocol.parseMissingChunksError(errorMessage)
                        if (missingChunksError != null && missingChunksError.missingIndices.isNotEmpty()) {
                            if (SyncHandshakeManager.hasCompletion(transactionId)) {
                                SyncHandshakeManager.cleanup(transactionId)
                                return true
                            }
                            retryAttempt++
                            currentCompletionWaiter =
                                SyncHandshakeManager.registerCompletionWaiter(transactionId)
                            currentErrorWaiter =
                                SyncHandshakeManager.registerErrorWaiter(transactionId)
                            sendSensorSessionChunks(
                                dataClient = dataClient,
                                transactionId = transactionId,
                                chunks = chunks,
                                chunkIndices = missingChunksError.missingIndices,
                                isRetry = true,
                                retryGeneration = missingChunksError.retryGeneration
                            )
                            delay(500L * (1 shl (retryAttempt - 1)) + (0..200).random().toLong())
                            continue
                        }
                    }
                    SyncHandshakeManager.cleanup(transactionId)
                    return false
                }
            }
        }
        SyncHandshakeManager.cleanup(transactionId)
        return false
    }

    private suspend fun cleanupAbandonedSensorSessionDataItems(dataClient: DataClient) {
        listOf(
            DataLayerPaths.SENSOR_SESSION_START_PREFIX,
            DataLayerPaths.SENSOR_SESSION_CHUNK_PREFIX
        ).forEach { pathPrefix ->
            try {
                val uri = Uri.Builder()
                    .scheme("wear")
                    .path(pathPrefix)
                    .build()
                val deletedCount = Tasks.await(dataClient.deleteDataItems(uri, DataClient.FILTER_PREFIX))
                if (deletedCount > 0) {
                    Log.d(
                        LOG_TAG,
                        "Removed $deletedCount abandoned sensor-session DataItem(s) for prefix=$pathPrefix"
                    )
                }
            } catch (exception: Exception) {
                Log.w(
                    LOG_TAG,
                    "Failed to remove abandoned sensor-session DataItems for prefix=$pathPrefix: ${exception.message}"
                )
            }
        }
    }

    private suspend fun cleanupSensorSessionTransactionDataItems(
        dataClient: DataClient,
        transactionId: String
    ) {
        listOf(
            DataLayerPaths.buildPath(DataLayerPaths.SYNC_REQUEST_PREFIX, transactionId),
            DataLayerPaths.buildPath(DataLayerPaths.SENSOR_SESSION_START_PREFIX, transactionId),
            DataLayerPaths.buildPath(DataLayerPaths.SENSOR_SESSION_CHUNK_PREFIX, transactionId)
        ).forEach { path ->
            try {
                val uri = Uri.Builder()
                    .scheme("wear")
                    .path(path)
                    .build()
                Tasks.await(dataClient.deleteDataItems(uri, DataClient.FILTER_PREFIX))
            } catch (exception: Exception) {
                Log.w(
                    LOG_TAG,
                    "Failed to clean up sensor-session DataItems for path=$path: ${exception.message}"
                )
            }
        }
    }
}
