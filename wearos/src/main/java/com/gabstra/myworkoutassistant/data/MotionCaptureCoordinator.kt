package com.gabstra.myworkoutassistant.data

import android.content.Context
import android.os.Build
import android.os.SystemClock
import android.util.Log
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureExerciseCandidate
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureEventRecord
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureEventType
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureExportService
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureJson
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureLabel
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureLabelKind
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureLabelMapper
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureReviewStatus
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSegmentDao
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSegmentEntity
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSegmentRecord
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSensorConfig
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSessionDao
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSessionEditor
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSessionEntity
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSessionRecord
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSessionStatus
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureWorkoutCatalog
import com.gabstra.myworkoutassistant.shared.workout.ui.WorkoutScreenState
import com.gabstra.myworkoutassistant.shared.workout.ui.WorkoutSessionPhase
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.repository.MotionSensorRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.BufferedWriter
import java.io.File
import java.util.UUID

data class MotionCaptureReviewSession(
    val session: MotionCaptureSessionRecord,
    val segments: List<MotionCaptureSegmentRecord>,
    val sessionDirectory: File
)

data class MotionCaptureUiState(
    val collectionEnabled: Boolean = false,
    val hasRequiredSensors: Boolean = false,
    val isCapturing: Boolean = false,
    val activeSessionId: UUID? = null,
    val latestReviewSession: MotionCaptureReviewSession? = null,
    val lastExportDirectory: String? = null
)

class MotionCaptureCoordinator(
    private val context: Context,
    private val appDatabase: AppDatabase,
    private val sensorRepository: MotionSensorRepository,
    private val scope: CoroutineScope,
    private val activeWorkoutHistoryIdProvider: () -> UUID?,
    private val appVersionProvider: () -> String
) {
    private val sessionDao: MotionCaptureSessionDao = appDatabase.motionCaptureSessionDao()
    private val segmentDao: MotionCaptureSegmentDao = appDatabase.motionCaptureSegmentDao()
    private val exportService = MotionCaptureExportService()
    private val sensorConfig = MotionCaptureSensorConfig()

    private val _uiState = MutableStateFlow(
        MotionCaptureUiState(
            collectionEnabled = MotionCapturePreferences.isEnabled(context),
            hasRequiredSensors = sensorRepository.hasRequiredSensors(sensorConfig)
        )
    )
    val uiState: StateFlow<MotionCaptureUiState> = _uiState.asStateFlow()

    private var activeSession: MotionCaptureSessionRecord? = null
    private var activeSegment: MotionCaptureSegmentRecord? = null
    private var activeLabel: MotionCaptureLabel? = null
    private var segmentSequenceIndex = 0
    private var captureJob: Job? = null
    private var currentChunkWriter: BufferedWriter? = null
    private var currentChunkFileName: String? = null
    private var currentChunkSampleCount = 0
    private var currentChunkIndex = 0
    private val eventsFileName = "events.csv"

    private fun sessionsRootDirectory(): File =
        File(context.filesDir, "motion_capture/sessions").apply { mkdirs() }

    private fun exportsRootDirectory(): File =
        File(context.filesDir, "motion_capture/exports").apply { mkdirs() }

    fun setCollectionEnabled(enabled: Boolean) {
        MotionCapturePreferences.setEnabled(context, enabled)
        _uiState.value = _uiState.value.copy(collectionEnabled = enabled)
        if (!enabled) {
            scope.launch { stopCapture(MotionCaptureSessionStatus.ABANDONED) }
        }
    }

    fun onScreenStateChanged(screenState: WorkoutScreenState) {
        if (!_uiState.value.collectionEnabled || !_uiState.value.hasRequiredSensors) {
            if (activeSession != null) {
                scope.launch { stopCapture(MotionCaptureSessionStatus.ABANDONED) }
            }
            return
        }

        val shouldCapture = screenState.sessionPhase == WorkoutSessionPhase.ACTIVE &&
            screenState.workoutState !is com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState.Completed
        if (!shouldCapture) {
            if (activeSession != null) {
                scope.launch { stopCapture(MotionCaptureSessionStatus.COMPLETED) }
            }
            return
        }

        scope.launch {
            startCaptureIfNeeded(screenState.selectedWorkout)
            restartSensorCollectionIfNeeded()
            syncLabel(screenState)
        }
    }

    suspend fun onPaused() {
        captureJob?.cancel()
        captureJob = null
        flushChunkWriter()
        _uiState.value = _uiState.value.copy(isCapturing = false)
    }

    suspend fun onWorkoutExited() {
        stopCapture(MotionCaptureSessionStatus.ABANDONED)
    }

    suspend fun confirmSegment(segmentId: UUID) {
        val segment = segmentDao.getById(segmentId)?.toRecord() ?: return
        val updated = MotionCaptureSessionEditor.confirmSegment(segment)
        segmentDao.insert(updated.toEntity())
        recordReviewChangedEvent(updated, "confirmed")
        refreshLatestReview()
    }

    suspend fun markSegmentRest(segmentId: UUID) {
        val segment = segmentDao.getById(segmentId)?.toRecord() ?: return
        val restLabel = segment.correctedLabel ?: segment.autoLabel.copy(
            kind = MotionCaptureLabelKind.REST
        )
        val updated = MotionCaptureSessionEditor.relabelSegment(
            segment = segment,
            correctedLabel = restLabel,
            reviewStatus = MotionCaptureReviewStatus.MARKED_REST
        )
        segmentDao.insert(updated.toEntity())
        recordReviewChangedEvent(updated, "marked_rest")
        refreshLatestReview()
    }

    suspend fun relabelSegment(
        segmentId: UUID,
        candidate: MotionCaptureExerciseCandidate
    ) {
        val segment = segmentDao.getById(segmentId)?.toRecord() ?: return
        val correctedLabel = segment.autoLabel.copy(
            kind = MotionCaptureLabelKind.EXERCISE,
            exerciseId = candidate.exerciseId,
            exerciseName = candidate.exerciseName,
            exerciseType = candidate.exerciseType,
            supersetId = candidate.supersetId,
            noRepExpected = candidate.noRepExpected
        )
        val updated = MotionCaptureSessionEditor.relabelSegment(
            segment = segment,
            correctedLabel = correctedLabel,
            reviewStatus = MotionCaptureReviewStatus.RELABELED
        )
        segmentDao.insert(updated.toEntity())
        recordReviewChangedEvent(updated, "relabeled")
        refreshLatestReview()
    }

    suspend fun dropSegment(segmentId: UUID) {
        val segment = segmentDao.getById(segmentId)?.toRecord() ?: return
        val updated = MotionCaptureSessionEditor.relabelSegment(
            segment = segment,
            correctedLabel = segment.correctedLabel ?: segment.autoLabel,
            reviewStatus = MotionCaptureReviewStatus.DROPPED
        )
        segmentDao.insert(updated.toEntity())
        recordReviewChangedEvent(updated, "dropped")
        refreshLatestReview()
    }

    suspend fun exportLatestReviewSession(): String? {
        val reviewSession = _uiState.value.latestReviewSession ?: return null
        val exportDirectory = withContext(Dispatchers.IO) {
            exportService.export(
                session = reviewSession.session,
                segments = reviewSession.segments.filter { it.reviewStatus != MotionCaptureReviewStatus.DROPPED },
                sessionDirectory = reviewSession.sessionDirectory,
                exportRootDirectory = exportsRootDirectory()
            )
        }
        _uiState.value = _uiState.value.copy(lastExportDirectory = exportDirectory.absolutePath)
        return exportDirectory.absolutePath
    }

    private suspend fun startCaptureIfNeeded(workout: Workout) {
        val historyId = activeWorkoutHistoryIdProvider()
        val currentSession = activeSession
        if (currentSession != null && currentSession.workoutId == workout.id) {
            if (currentSession.workoutHistoryId == historyId || historyId == null) {
                return
            }
            if (currentSession.workoutHistoryId == null && historyId != null) {
                val updatedSession = currentSession.copy(workoutHistoryId = historyId)
                sessionDao.insert(updatedSession.toEntity())
                activeSession = updatedSession
                return
            }
        }
        if (currentSession != null) {
            stopCapture(MotionCaptureSessionStatus.ABANDONED)
        }
        val sessionId = UUID.randomUUID()
        val sessionDirectoryName = sessionId.toString()
        val candidates = MotionCaptureWorkoutCatalog.buildCandidates(workout)
        val session = MotionCaptureSessionRecord(
            id = sessionId,
            workoutId = workout.id,
            workoutHistoryId = historyId,
            status = MotionCaptureSessionStatus.ACTIVE,
            startedAtEpochMs = System.currentTimeMillis(),
            endedAtEpochMs = null,
            deviceManufacturer = Build.MANUFACTURER,
            deviceModel = Build.MODEL,
            deviceName = Build.DEVICE,
            appVersion = appVersionProvider(),
            sessionDirectoryName = sessionDirectoryName,
            sensorConfig = sensorConfig,
            exerciseCandidates = candidates
        )
        sessionDao.insert(session.toEntity())
        activeSession = session
        activeLabel = null
        activeSegment = null
        segmentSequenceIndex = 0
        currentChunkIndex = 0
        currentChunkSampleCount = 0
        currentChunkFileName = null
        val sessionDirectory = sessionsRootDirectory().resolve(sessionDirectoryName).apply { mkdirs() }
        initializeEventsFile(sessionDirectory)
        startSensorCollection(session)
    }

    private suspend fun syncLabel(screenState: WorkoutScreenState) {
        val session = activeSession ?: return
        val previousLabel = activeLabel
        val previousSegment = activeSegment
        val newLabel = MotionCaptureLabelMapper.map(screenState.workoutState, screenState.selectedWorkout)
        val transitionEpochMs = System.currentTimeMillis()
        val transitionElapsedRealtimeNanos = SystemClock.elapsedRealtimeNanos()
        if (newLabel == null) {
            recordExitEvents(previousLabel, previousSegment, transitionEpochMs, transitionElapsedRealtimeNanos)
            closeActiveSegment(transitionEpochMs, transitionElapsedRealtimeNanos)
            activeLabel = null
            return
        }
        if (activeLabel == newLabel && activeSegment != null) {
            return
        }
        recordExitEvents(previousLabel, previousSegment, transitionEpochMs, transitionElapsedRealtimeNanos)
        closeActiveSegment(transitionEpochMs, transitionElapsedRealtimeNanos)
        val startedAtEpochMs = transitionEpochMs
        val startedAtElapsedRealtimeNanos = transitionElapsedRealtimeNanos
        var segment = MotionCaptureSessionEditor.startSegment(
            sessionId = session.id,
            sequenceIndex = segmentSequenceIndex++,
            label = newLabel,
            startedAtEpochMs = startedAtEpochMs,
            startedAtElapsedRealtimeNanos = startedAtElapsedRealtimeNanos,
            initialChunkFileName = currentChunkFileName
        )
        currentChunkFileName?.let {
            segment = MotionCaptureSessionEditor.appendChunkReference(segment, it)
        }
        segmentDao.insert(segment.toEntity())
        activeSegment = segment
        activeLabel = newLabel
        recordEnterEvents(previousLabel, newLabel, segment, startedAtEpochMs, startedAtElapsedRealtimeNanos)
    }

    private suspend fun closeActiveSegment(
        endedAtEpochMs: Long,
        endedAtElapsedRealtimeNanos: Long
    ) {
        val segment = activeSegment ?: return
        val updated = MotionCaptureSessionEditor.closeSegment(
            segment = segment,
            endedAtEpochMs = endedAtEpochMs,
            endedAtElapsedRealtimeNanos = endedAtElapsedRealtimeNanos
        )
        segmentDao.insert(updated.toEntity())
        activeSegment = null
    }

    private suspend fun stopCapture(status: MotionCaptureSessionStatus) {
        val endedAtEpochMs = System.currentTimeMillis()
        val endedAtElapsedRealtimeNanos = SystemClock.elapsedRealtimeNanos()
        recordExitEvents(activeLabel, activeSegment, endedAtEpochMs, endedAtElapsedRealtimeNanos)
        closeActiveSegment(endedAtEpochMs, endedAtElapsedRealtimeNanos)
        activeLabel = null
        captureJob?.cancel()
        captureJob = null
        flushChunkWriter()
        val session = activeSession ?: return
        val updated = session.copy(
            status = status,
            endedAtEpochMs = endedAtEpochMs
        )
        sessionDao.insert(updated.toEntity())
        activeSession = null
        _uiState.value = _uiState.value.copy(
            isCapturing = false,
            activeSessionId = null
        )
        refreshLatestReview()
    }

    private suspend fun refreshLatestReview() {
        val latest = sessionDao.getLatestByStatus(MotionCaptureSessionStatus.COMPLETED.name) ?: return
        val latestRecord = latest.toRecord()
        val segments = segmentDao.getBySessionId(latest.id).map { it.toRecord() }
        val sessionDirectory = sessionsRootDirectory().resolve(latest.sessionDirectoryName)
        _uiState.value = _uiState.value.copy(
            latestReviewSession = MotionCaptureReviewSession(
                session = latestRecord,
                segments = segments,
                sessionDirectory = sessionDirectory
            )
        )
    }

    private fun restartSensorCollectionIfNeeded() {
        val session = activeSession ?: return
        if (captureJob?.isActive == true) return
        startSensorCollection(session)
    }

    private fun startSensorCollection(session: MotionCaptureSessionRecord) {
        captureJob?.cancel()
        captureJob = scope.launch(Dispatchers.IO) {
            sensorRepository.sampleFlow(sensorConfig).collect { sample ->
                writeSample(sample)
            }
        }
        _uiState.value = _uiState.value.copy(
            isCapturing = true,
            activeSessionId = session.id
        )
    }

    private suspend fun writeSample(sample: com.gabstra.myworkoutassistant.shared.motion.MotionSensorSample) {
        val session = activeSession ?: return
        ensureChunkWriter(session)
        currentChunkWriter?.apply {
            append(
                "${sample.sensorType},${sample.epochTimeMs},${sample.elapsedRealtimeNanos}," +
                    "${sample.accuracy},${sample.x},${sample.y},${sample.z},${sample.w ?: ""}\n"
            )
            currentChunkSampleCount += 1
            if (currentChunkSampleCount >= sensorConfig.chunkSampleCount) {
                flush()
                close()
                currentChunkWriter = null
                currentChunkFileName = null
                currentChunkSampleCount = 0
            }
        }
    }

    private suspend fun recordEnterEvents(
        previousLabel: MotionCaptureLabel?,
        newLabel: MotionCaptureLabel,
        segment: MotionCaptureSegmentRecord,
        epochTimeMs: Long,
        elapsedRealtimeNanos: Long
    ) {
        if (newLabel.kind == MotionCaptureLabelKind.EXERCISE) {
            if (previousLabel?.exerciseId != newLabel.exerciseId) {
                writeEvent(
                    MotionCaptureEventRecord(
                        eventType = MotionCaptureEventType.NEXT_EXERCISE_ENTERED,
                        epochTimeMs = epochTimeMs,
                        elapsedRealtimeNanos = elapsedRealtimeNanos,
                        stateName = newLabel.stateName,
                        exerciseId = newLabel.exerciseId,
                        exerciseName = newLabel.exerciseName,
                        setId = newLabel.setId,
                        setIndex = newLabel.setIndex,
                        exerciseType = newLabel.exerciseType,
                        noRepExpected = newLabel.noRepExpected,
                        segmentId = segment.id
                    ),
                    segment.sessionId
                )
            }
            writeEvent(
                MotionCaptureEventRecord(
                    eventType = MotionCaptureEventType.ENTERED_SET,
                    epochTimeMs = epochTimeMs,
                    elapsedRealtimeNanos = elapsedRealtimeNanos,
                    stateName = newLabel.stateName,
                    exerciseId = newLabel.exerciseId,
                    exerciseName = newLabel.exerciseName,
                    setId = newLabel.setId,
                    setIndex = newLabel.setIndex,
                    exerciseType = newLabel.exerciseType,
                    noRepExpected = newLabel.noRepExpected,
                    segmentId = segment.id
                ),
                segment.sessionId
            )
            if (newLabel.noRepExpected) {
                writeEvent(
                    MotionCaptureEventRecord(
                        eventType = MotionCaptureEventType.TIMER_STARTED,
                        epochTimeMs = epochTimeMs,
                        elapsedRealtimeNanos = elapsedRealtimeNanos,
                        stateName = newLabel.stateName,
                        exerciseId = newLabel.exerciseId,
                        exerciseName = newLabel.exerciseName,
                        setId = newLabel.setId,
                        setIndex = newLabel.setIndex,
                        exerciseType = newLabel.exerciseType,
                        noRepExpected = true,
                        segmentId = segment.id
                    ),
                    segment.sessionId
                )
            }
        } else if (newLabel.kind == MotionCaptureLabelKind.REST) {
            writeEvent(
                MotionCaptureEventRecord(
                    eventType = MotionCaptureEventType.REST_STARTED,
                    epochTimeMs = epochTimeMs,
                    elapsedRealtimeNanos = elapsedRealtimeNanos,
                    stateName = newLabel.stateName,
                    exerciseId = newLabel.exerciseId,
                    exerciseName = newLabel.exerciseName,
                    setId = newLabel.setId,
                    exerciseType = newLabel.exerciseType,
                    noRepExpected = newLabel.noRepExpected,
                    segmentId = segment.id
                ),
                segment.sessionId
            )
        }
    }

    private suspend fun recordExitEvents(
        previousLabel: MotionCaptureLabel?,
        previousSegment: MotionCaptureSegmentRecord?,
        epochTimeMs: Long,
        elapsedRealtimeNanos: Long
    ) {
        if (previousLabel?.kind != MotionCaptureLabelKind.EXERCISE) {
            return
        }
        writeEvent(
            MotionCaptureEventRecord(
                eventType = MotionCaptureEventType.SET_COMPLETED,
                epochTimeMs = epochTimeMs,
                elapsedRealtimeNanos = elapsedRealtimeNanos,
                stateName = previousLabel.stateName,
                exerciseId = previousLabel.exerciseId,
                exerciseName = previousLabel.exerciseName,
                setId = previousLabel.setId,
                setIndex = previousLabel.setIndex,
                exerciseType = previousLabel.exerciseType,
                noRepExpected = previousLabel.noRepExpected,
                segmentId = previousSegment?.id
            ),
            previousSegment?.sessionId
        )
        if (previousLabel.noRepExpected) {
            writeEvent(
                MotionCaptureEventRecord(
                    eventType = MotionCaptureEventType.TIMER_FINISHED,
                    epochTimeMs = epochTimeMs,
                    elapsedRealtimeNanos = elapsedRealtimeNanos,
                    stateName = previousLabel.stateName,
                    exerciseId = previousLabel.exerciseId,
                    exerciseName = previousLabel.exerciseName,
                    setId = previousLabel.setId,
                    setIndex = previousLabel.setIndex,
                    exerciseType = previousLabel.exerciseType,
                    noRepExpected = true,
                    segmentId = previousSegment?.id
                ),
                previousSegment?.sessionId
            )
        }
    }

    private suspend fun recordReviewChangedEvent(
        segment: MotionCaptureSegmentRecord,
        notes: String
    ) {
        val label = segment.correctedLabel ?: segment.autoLabel
        writeEvent(
            MotionCaptureEventRecord(
                eventType = MotionCaptureEventType.SEGMENT_REVIEW_CHANGED,
                epochTimeMs = System.currentTimeMillis(),
                elapsedRealtimeNanos = SystemClock.elapsedRealtimeNanos(),
                stateName = label.stateName,
                exerciseId = label.exerciseId,
                exerciseName = label.exerciseName,
                setId = label.setId,
                setIndex = label.setIndex,
                exerciseType = label.exerciseType,
                noRepExpected = label.noRepExpected,
                segmentId = segment.id,
                reviewStatus = segment.reviewStatus,
                notes = notes
            ),
            segment.sessionId
        )
    }

    private fun initializeEventsFile(sessionDirectory: File) {
        val eventsFile = sessionDirectory.resolve(eventsFileName)
        if (eventsFile.exists()) {
            return
        }
        eventsFile.writeText(
            "eventType,epochTimeMs,elapsedRealtimeNanos,stateName,exerciseId,exerciseName," +
                "setId,setIndex,exerciseType,noRepExpected,segmentId,reviewStatus,notes\n"
        )
    }

    private suspend fun writeEvent(
        event: MotionCaptureEventRecord,
        sessionId: UUID?
    ) {
        val sessionDirectoryName = when {
            activeSession?.id == sessionId -> activeSession?.sessionDirectoryName
            sessionId != null -> sessionDao.getById(sessionId)?.sessionDirectoryName
            else -> null
        } ?: return
        val sessionDirectory = sessionsRootDirectory().resolve(sessionDirectoryName).apply { mkdirs() }
        initializeEventsFile(sessionDirectory)
        withContext(Dispatchers.IO) {
            sessionDirectory.resolve(eventsFileName).appendText(
                listOf(
                    event.eventType.name.lowercase(),
                    event.epochTimeMs.toString(),
                    event.elapsedRealtimeNanos.toString(),
                    csvValue(event.stateName),
                    csvValue(event.exerciseId?.toString()),
                    csvValue(event.exerciseName),
                    csvValue(event.setId?.toString()),
                    csvValue(event.setIndex?.toString()),
                    csvValue(event.exerciseType?.name),
                    event.noRepExpected.toString(),
                    csvValue(event.segmentId?.toString()),
                    csvValue(event.reviewStatus?.name),
                    csvValue(event.notes)
                ).joinToString(",") + "\n"
            )
        }
    }

    private fun csvValue(value: String?): String {
        if (value.isNullOrEmpty()) {
            return ""
        }
        return "\"${value.replace("\"", "\"\"")}\""
    }

    private suspend fun ensureChunkWriter(session: MotionCaptureSessionRecord) {
        if (currentChunkWriter != null) return
        currentChunkIndex += 1
        currentChunkSampleCount = 0
        val chunkFileName = "chunk_${currentChunkIndex.toString().padStart(5, '0')}.csv"
        val sessionDirectory = sessionsRootDirectory().resolve(session.sessionDirectoryName).apply { mkdirs() }
        currentChunkFileName = chunkFileName
        currentChunkWriter = withContext(Dispatchers.IO) {
            File(sessionDirectory, chunkFileName).bufferedWriter().also { writer ->
                writer.write("sensorType,epochTimeMs,elapsedRealtimeNanos,accuracy,x,y,z,w\n")
            }
        }
        val segment = activeSegment
        if (segment != null) {
            val updated = MotionCaptureSessionEditor.appendChunkReference(segment, chunkFileName)
            segmentDao.insert(updated.toEntity())
            activeSegment = updated
        }
    }

    private suspend fun flushChunkWriter() {
        withContext(Dispatchers.IO) {
            currentChunkWriter?.flush()
            currentChunkWriter?.close()
            currentChunkWriter = null
            currentChunkFileName = null
            currentChunkSampleCount = 0
        }
    }

    private fun MotionCaptureSessionRecord.toEntity(): MotionCaptureSessionEntity =
        MotionCaptureSessionEntity(
            id = id,
            workoutId = workoutId,
            workoutHistoryId = workoutHistoryId,
            status = status.name,
            startedAtEpochMs = startedAtEpochMs,
            endedAtEpochMs = endedAtEpochMs,
            deviceManufacturer = deviceManufacturer,
            deviceModel = deviceModel,
            deviceName = deviceName,
            appVersion = appVersion,
            sessionDirectoryName = sessionDirectoryName,
            sensorConfigJson = MotionCaptureJson.sensorConfigToJson(sensorConfig),
            exerciseCandidatesJson = MotionCaptureJson.candidateListToJson(exerciseCandidates)
        )

    private fun MotionCaptureSessionEntity.toRecord(): MotionCaptureSessionRecord =
        MotionCaptureSessionRecord(
            id = id,
            workoutId = workoutId,
            workoutHistoryId = workoutHistoryId,
            status = MotionCaptureSessionStatus.valueOf(status),
            startedAtEpochMs = startedAtEpochMs,
            endedAtEpochMs = endedAtEpochMs,
            deviceManufacturer = deviceManufacturer,
            deviceModel = deviceModel,
            deviceName = deviceName,
            appVersion = appVersion,
            sessionDirectoryName = sessionDirectoryName,
            sensorConfig = MotionCaptureJson.sensorConfigFromJson(sensorConfigJson),
            exerciseCandidates = MotionCaptureJson.candidateListFromJson(exerciseCandidatesJson)
        )

    private fun MotionCaptureSegmentRecord.toEntity(): MotionCaptureSegmentEntity =
        MotionCaptureSegmentEntity(
            id = id,
            sessionId = sessionId,
            sequenceIndex = sequenceIndex,
            startedAtEpochMs = startedAtEpochMs,
            endedAtEpochMs = endedAtEpochMs,
            startedAtElapsedRealtimeNanos = startedAtElapsedRealtimeNanos,
            endedAtElapsedRealtimeNanos = endedAtElapsedRealtimeNanos,
            stateName = stateName,
            autoLabelJson = MotionCaptureJson.labelToJson(autoLabel),
            correctedLabelJson = correctedLabel?.let(MotionCaptureJson::labelToJson),
            reviewStatus = reviewStatus.name,
            chunkFileNamesJson = MotionCaptureJson.stringListToJson(chunkFileNames)
        )

    private fun MotionCaptureSegmentEntity.toRecord(): MotionCaptureSegmentRecord =
        MotionCaptureSegmentRecord(
            id = id,
            sessionId = sessionId,
            sequenceIndex = sequenceIndex,
            startedAtEpochMs = startedAtEpochMs,
            endedAtEpochMs = endedAtEpochMs,
            startedAtElapsedRealtimeNanos = startedAtElapsedRealtimeNanos,
            endedAtElapsedRealtimeNanos = endedAtElapsedRealtimeNanos,
            stateName = stateName,
            autoLabel = MotionCaptureJson.labelFromJson(autoLabelJson),
            correctedLabel = correctedLabelJson?.let(MotionCaptureJson::labelFromJson),
            reviewStatus = MotionCaptureReviewStatus.valueOf(reviewStatus),
            chunkFileNames = MotionCaptureJson.stringListFromJson(chunkFileNamesJson)
        )
}
