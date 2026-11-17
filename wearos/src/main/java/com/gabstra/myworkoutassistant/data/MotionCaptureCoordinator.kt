package com.gabstra.myworkoutassistant.data

import android.content.Context
import android.os.Build
import android.os.SystemClock
import android.util.Log
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureChunkCompressor
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureDetailLevel
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureExerciseCandidate
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureEventRecord
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureEventType
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureExportService
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureJson
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureLabel
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureLabelKind
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureLabelMapper
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureReviewStatus
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSampleRate
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSegmentDao
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSegmentEntity
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSegmentRecord
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSessionDao
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSessionEditor
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSessionEntity
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSessionRecord
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSessionStatus
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureWorkoutCatalog
import com.gabstra.myworkoutassistant.shared.motion.MotionSensorType
import com.gabstra.myworkoutassistant.shared.workout.ui.WorkoutScreenState
import com.gabstra.myworkoutassistant.shared.workout.ui.WorkoutSessionPhase
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.reps.RepDetector
import com.gabstra.myworkoutassistant.reps.StillnessTracker
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
    val detailLevel: MotionCaptureDetailLevel = MotionCaptureDetailLevel.FULL,
    val sampleRate: MotionCaptureSampleRate = MotionCaptureSampleRate.HZ_50,
    val hasRequiredSensors: Boolean = false,
    val isCapturing: Boolean = false,
    val activeSessionId: UUID? = null,
    val latestReviewSession: MotionCaptureReviewSession? = null,
    val lastExportDirectory: String? = null
)

/**
 * Cheap snapshot of everything the motion-capture label depends on. Two ticks with the same key
 * produce the same [MotionCaptureLabelMapper] result.
 */
private data class MotionCaptureLabelKey(
    val workoutId: UUID,
    val workoutStateType: Class<out WorkoutState>,
    val exerciseId: UUID?,
    val setId: UUID?,
    val setIndex: UInt?,
    val isWarmupSet: Boolean,
    val isCalibrationSet: Boolean,
    val isAutoRegulationSet: Boolean,
    val isIntraSetRest: Boolean
)

/**
 * Everything that can change the outcome of [MotionCaptureCoordinator.onScreenStateChanged]'s
 * launched work. Timer progress callbacks rebuild the screen state every tick; when this key is
 * unchanged the launch is redundant.
 */
private data class MotionCaptureTickKey(
    val labelKey: MotionCaptureLabelKey,
    val sessionPhase: WorkoutSessionPhase,
    val collectionEnabled: Boolean,
    val detailLevel: MotionCaptureDetailLevel,
    val sampleRate: MotionCaptureSampleRate,
    val hasRequiredSensors: Boolean,
    val workoutHistoryId: UUID?,
    val activeSessionId: UUID?,
    val activeSessionWorkoutId: UUID?,
    val activeSessionWorkoutHistoryId: UUID?,
    val isCaptureJobActive: Boolean
)

class MotionCaptureCoordinator(
    private val context: Context,
    private val appDatabase: AppDatabase,
    private val sensorRepository: MotionSensorRepository,
    private val scope: CoroutineScope,
    private val activeWorkoutHistoryIdProvider: () -> UUID?,
    private val appVersionProvider: () -> String,
    private val onStillnessChanged: (Boolean) -> Unit = {}
) {
    private val sessionDao: MotionCaptureSessionDao = appDatabase.motionCaptureSessionDao()
    private val segmentDao: MotionCaptureSegmentDao = appDatabase.motionCaptureSegmentDao()
    private val exportService = MotionCaptureExportService()
    private var sensorConfig =
        MotionCaptureDetailLevel.FULL.toSensorConfig(MotionCaptureSampleRate.HZ_50)

    init {
        sensorRepository.logInventory()
    }

    private val _uiState = MutableStateFlow(
        MotionCaptureUiState(
            // Motion capture is on by default; the workout settings toggle overrides it per session.
            collectionEnabled = true,
            hasRequiredSensors = sensorRepository.hasCoreSensors()
        )
    )
    val uiState: StateFlow<MotionCaptureUiState> = _uiState.asStateFlow()

    private var activeSession: MotionCaptureSessionRecord? = null
    private var activeSegment: MotionCaptureSegmentRecord? = null
    private var activeLabel: MotionCaptureLabel? = null
    private var lastObservedWorkoutState: com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState? = null
    private var segmentSequenceIndex = 0
    private var captureJob: Job? = null
    private var currentChunkWriter: BufferedWriter? = null
    private var currentChunkFileName: String? = null
    private var currentChunkSampleCount = 0
    private var currentChunkIndex = 0
    private var lowStorageAbortTriggered = false
    private var captureToggledOnManually = false
    /** Per-workout override; null means "use the preference". Scoped by workout id. */
    private var sessionOverrideEnabled: Boolean? = null
    /** Per-workout detail override; null means [MotionCaptureDetailLevel.FULL]. */
    private var sessionOverrideDetailLevel: MotionCaptureDetailLevel? = null
    /** Per-workout sample-rate override; null means [MotionCaptureSampleRate.HZ_50]. */
    private var sessionOverrideSampleRate: MotionCaptureSampleRate? = null
    private var overrideWorkoutId: UUID? = null
    private var currentWorkoutId: UUID? = null
    private var lastScreenState: WorkoutScreenState? = null
    private var repDetector: RepDetector? = null
    private var repDetectorSensor: MotionSensorType? = null
    private val stillnessTracker = StillnessTracker()
    private var lastStillness = true
    private val eventsFileName = "events.csv"
    private var lastProcessedTickKey: MotionCaptureTickKey? = null
    private var lastProcessedWorkout: Workout? = null
    private var cachedLabelKey: MotionCaptureLabelKey? = null
    private var cachedLabelWorkout: Workout? = null
    private var cachedLabel: MotionCaptureLabel? = null
    private var cachedCandidatesWorkout: Workout? = null
    private var cachedCandidates: List<MotionCaptureExerciseCandidate> = emptyList()

    companion object {
        private const val TAG = "MotionCapture"
        private const val MIN_FREE_BYTES_FOR_CAPTURE = 200L * 1024 * 1024
    }

    private fun sessionsRootDirectory(): File =
        File(context.filesDir, "motion_capture/sessions").apply { mkdirs() }

    private fun exportsRootDirectory(): File =
        File(context.filesDir, "motion_capture/exports").apply { mkdirs() }

    private fun labelKeyFor(workoutState: WorkoutState, workout: Workout): MotionCaptureLabelKey =
        when (workoutState) {
            is WorkoutState.Set -> MotionCaptureLabelKey(
                workoutId = workout.id,
                workoutStateType = workoutState.javaClass,
                exerciseId = workoutState.exerciseId,
                setId = workoutState.set.id,
                setIndex = workoutState.setIndex,
                isWarmupSet = workoutState.isWarmupSet,
                isCalibrationSet = workoutState.isCalibrationSet,
                isAutoRegulationSet = workoutState.isAutoRegulationWorkSet,
                isIntraSetRest = false
            )
            is WorkoutState.Rest -> MotionCaptureLabelKey(
                workoutId = workout.id,
                workoutStateType = workoutState.javaClass,
                exerciseId = workoutState.exerciseId,
                setId = workoutState.set.id,
                setIndex = null,
                isWarmupSet = false,
                isCalibrationSet = false,
                isAutoRegulationSet = false,
                isIntraSetRest = workoutState.isIntraSetRest
            )
            else -> MotionCaptureLabelKey(
                workoutId = workout.id,
                workoutStateType = workoutState.javaClass,
                exerciseId = null,
                setId = null,
                setIndex = null,
                isWarmupSet = false,
                isCalibrationSet = false,
                isAutoRegulationSet = false,
                isIntraSetRest = false
            )
        }

    private fun tickKeyFor(screenState: WorkoutScreenState): MotionCaptureTickKey {
        val uiState = _uiState.value
        val session = activeSession
        return MotionCaptureTickKey(
            labelKey = labelKeyFor(screenState.workoutState, screenState.selectedWorkout),
            sessionPhase = screenState.sessionPhase,
            collectionEnabled = uiState.collectionEnabled,
            detailLevel = uiState.detailLevel,
            sampleRate = uiState.sampleRate,
            hasRequiredSensors = uiState.hasRequiredSensors,
            workoutHistoryId = activeWorkoutHistoryIdProvider(),
            activeSessionId = session?.id,
            activeSessionWorkoutId = session?.workoutId,
            activeSessionWorkoutHistoryId = session?.workoutHistoryId,
            isCaptureJobActive = captureJob?.isActive == true
        )
    }

    /** Deterministic per workout object; rebuilt only when the workout instance changes. */
    private fun candidatesFor(workout: Workout): List<MotionCaptureExerciseCandidate> {
        if (cachedCandidatesWorkout === workout) {
            return cachedCandidates
        }
        return MotionCaptureWorkoutCatalog.buildCandidates(workout).also {
            cachedCandidatesWorkout = workout
            cachedCandidates = it
        }
    }

    /** Reuses the mapper result while the label inputs and workout instance are unchanged. */
    private fun resolveLabel(
        screenState: WorkoutScreenState,
        labelKey: MotionCaptureLabelKey
    ): MotionCaptureLabel? {
        if (cachedLabelKey == labelKey && cachedLabelWorkout === screenState.selectedWorkout) {
            return cachedLabel
        }
        return MotionCaptureLabelMapper.map(
            screenState.workoutState,
            screenState.selectedWorkout
        ).also {
            cachedLabelKey = labelKey
            cachedLabelWorkout = screenState.selectedWorkout
            cachedLabel = it
        }
    }

    /**
     * Per-workout override of the motion-capture default. Not persisted: the next workout
     * starts from the preference again.
     */
    fun setSessionCollectionEnabled(enabled: Boolean) {
        sessionOverrideEnabled = enabled
        overrideWorkoutId = currentWorkoutId
        captureToggledOnManually = enabled
        _uiState.value = _uiState.value.copy(collectionEnabled = enabled)
        // The toggle may be flipped back before another screen-state tick is processed, so force
        // the next onScreenStateChanged call to run capture/label work.
        lastProcessedTickKey = null
        if (!enabled) {
            scope.launch {
                if (activeSession != null) stopCapture(MotionCaptureSessionStatus.ABANDONED)
            }
        } else {
            // Turning it back on mid-workout starts recording immediately.
            lastScreenState?.let { onScreenStateChanged(it) }
        }
    }

    /**
     * Per-workout detail level, mirroring [setSessionCollectionEnabled]: resets to FULL for the
     * next workout. A switch mid-session restarts sensor collection with the new config.
     */
    fun setSessionDetailLevel(level: MotionCaptureDetailLevel) {
        if (_uiState.value.detailLevel == level) return
        sessionOverrideDetailLevel = level
        overrideWorkoutId = currentWorkoutId
        applyDetailLevel(level)
        lastProcessedTickKey = null
        scope.launch {
            updateActiveSessionSensorConfig()
            // Cancel the in-flight job so the next screen-state tick restarts collection with
            // the new sensor set instead of keeping the old registration.
            captureJob?.cancel()
            captureJob = null
            lastProcessedTickKey = null
            lastScreenState?.let { onScreenStateChanged(it) }
        }
    }

    private fun applyDetailLevel(level: MotionCaptureDetailLevel) {
        if (_uiState.value.detailLevel == level) return
        sensorConfig = level.toSensorConfig(_uiState.value.sampleRate)
        _uiState.value = _uiState.value.copy(detailLevel = level)
    }

    /**
     * Per-workout sample rate, mirroring [setSessionDetailLevel]: resets to [MotionCaptureSampleRate.HZ_50]
     * for the next workout. A switch mid-session restarts sensor collection with the new config.
     */
    fun setSessionSampleRate(rate: MotionCaptureSampleRate) {
        if (_uiState.value.sampleRate == rate) return
        sessionOverrideSampleRate = rate
        overrideWorkoutId = currentWorkoutId
        applySampleRate(rate)
        lastProcessedTickKey = null
        scope.launch {
            updateActiveSessionSensorConfig()
            // Cancel the in-flight job so the next screen-state tick restarts collection with
            // the new rate instead of keeping the old registration.
            captureJob?.cancel()
            captureJob = null
            lastProcessedTickKey = null
            lastScreenState?.let { onScreenStateChanged(it) }
        }
    }

    private fun applySampleRate(rate: MotionCaptureSampleRate) {
        if (_uiState.value.sampleRate == rate) return
        sensorConfig = _uiState.value.detailLevel.toSensorConfig(rate)
        _uiState.value = _uiState.value.copy(sampleRate = rate)
    }

    /** Keeps the self-describing session record in sync with a mid-session level switch. */
    private suspend fun updateActiveSessionSensorConfig() {
        val session = activeSession ?: return
        val updatedConfig = sensorConfig.copy(
            observedSensors = sensorRepository.observedSensors(sensorConfig).sorted().toList(),
            userInitiated = session.sensorConfig.userInitiated
        )
        if (updatedConfig == session.sensorConfig) return
        val updated = session.copy(sensorConfig = updatedConfig)
        sessionDao.insert(updated.toEntity())
        activeSession = updated
    }

    fun onScreenStateChanged(screenState: WorkoutScreenState) {
        lastScreenState = screenState
        currentWorkoutId = screenState.selectedWorkout.id
        val enabled = if (overrideWorkoutId == currentWorkoutId) {
            sessionOverrideEnabled == true
        } else {
            true
        }
        val detailLevel = if (overrideWorkoutId == currentWorkoutId) {
            sessionOverrideDetailLevel ?: MotionCaptureDetailLevel.FULL
        } else {
            MotionCaptureDetailLevel.FULL
        }
        val sampleRate = if (overrideWorkoutId == currentWorkoutId) {
            sessionOverrideSampleRate ?: MotionCaptureSampleRate.HZ_50
        } else {
            MotionCaptureSampleRate.HZ_50
        }
        applyDetailLevel(detailLevel)
        applySampleRate(sampleRate)
        if (_uiState.value.collectionEnabled != enabled) {
            _uiState.value = _uiState.value.copy(collectionEnabled = enabled)
        }
        val tickKey = tickKeyFor(screenState)
        if (tickKey == lastProcessedTickKey && lastProcessedWorkout === screenState.selectedWorkout) {
            // Keep the previous-state snapshot fresh for exit-event rep counts without doing
            // capture or label work on redundant timer ticks.
            if (lastObservedWorkoutState !== screenState.workoutState) {
                lastObservedWorkoutState = screenState.workoutState
            }
            return
        }
        lastProcessedTickKey = tickKey
        lastProcessedWorkout = screenState.selectedWorkout
        if (!enabled || !_uiState.value.hasRequiredSensors) {
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
            val captureSettled = startCaptureIfNeeded(screenState.selectedWorkout)
            restartSensorCollectionIfNeeded()
            syncLabel(screenState, tickKey.labelKey)
            if (!captureSettled) {
                // Low storage: retry on the next tick so capture starts once space is available.
                lastProcessedTickKey = null
            }
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

    private suspend fun startCaptureIfNeeded(workout: Workout): Boolean {
        val usableSpace = withContext(Dispatchers.IO) { sessionsRootDirectory().usableSpace }
        if (usableSpace < MIN_FREE_BYTES_FOR_CAPTURE) {
            Log.e(TAG, "Motion capture not started - low storage (free=$usableSpace bytes)")
            return false
        }
        val historyId = activeWorkoutHistoryIdProvider()
        val currentSession = activeSession
        if (currentSession != null && currentSession.workoutId == workout.id) {
            if (currentSession.workoutHistoryId == historyId || historyId == null) {
                return true
            }
            if (currentSession.workoutHistoryId == null) {
                val updatedSession = currentSession.copy(workoutHistoryId = historyId)
                sessionDao.insert(updatedSession.toEntity())
                activeSession = updatedSession
                return true
            }
        }
        if (currentSession != null) {
            stopCapture(MotionCaptureSessionStatus.ABANDONED)
        }
        val sessionId = UUID.randomUUID()
        val sessionDirectoryName = sessionId.toString()
        val candidates = candidatesFor(workout)
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
            sensorConfig = sensorConfig.copy(
                observedSensors = sensorRepository.observedSensors(sensorConfig).sorted().toList(),
                userInitiated = captureToggledOnManually
            ),
            exerciseCandidates = candidates
        )
        sessionDao.insert(session.toEntity())
        activeSession = session
        activeLabel = null
        lastObservedWorkoutState = null
        activeSegment = null
        segmentSequenceIndex = 0
        currentChunkIndex = 0
        currentChunkSampleCount = 0
        currentChunkFileName = null
        lowStorageAbortTriggered = false
        captureToggledOnManually = false
        withContext(Dispatchers.IO) {
            val sessionDirectory = sessionsRootDirectory().resolve(sessionDirectoryName).apply { mkdirs() }
            initializeEventsFile(sessionDirectory)
        }
        startSensorCollection(session)
        return true
    }

    private suspend fun syncLabel(
        screenState: WorkoutScreenState,
        labelKey: MotionCaptureLabelKey
    ) {
        val session = activeSession ?: return
        val previousLabel = activeLabel
        val previousSegment = activeSegment
        val previousWorkoutState = lastObservedWorkoutState
        lastObservedWorkoutState = screenState.workoutState
        val newLabel = resolveLabel(screenState, labelKey)
        val transitionEpochMs = System.currentTimeMillis()
        val transitionElapsedRealtimeNanos = SystemClock.elapsedRealtimeNanos()
        if (newLabel == null) {
            recordExitEvents(previousLabel, previousSegment, transitionEpochMs, transitionElapsedRealtimeNanos, previousWorkoutState)
            closeActiveSegment(transitionEpochMs, transitionElapsedRealtimeNanos)
            activeLabel = null
            return
        }
        if (activeLabel == newLabel && activeSegment != null) {
            return
        }
        recordExitEvents(previousLabel, previousSegment, transitionEpochMs, transitionElapsedRealtimeNanos, previousWorkoutState)
        closeActiveSegment(transitionEpochMs, transitionElapsedRealtimeNanos)
        if (newLabel.kind == MotionCaptureLabelKind.EXERCISE && !newLabel.noRepExpected) {
            repDetector?.reset()
        }
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
        stillnessTracker.reset()
        notifyStillness(true)
        val endedAtEpochMs = System.currentTimeMillis()
        val endedAtElapsedRealtimeNanos = SystemClock.elapsedRealtimeNanos()
        recordExitEvents(activeLabel, activeSegment, endedAtEpochMs, endedAtElapsedRealtimeNanos, lastObservedWorkoutState)
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
        gzipSessionChunks(session.id, session.sessionDirectoryName)
        _uiState.value = _uiState.value.copy(
            isCapturing = false,
            activeSessionId = null
        )
        refreshLatestReview()
    }

    private suspend fun gzipSessionChunks(sessionId: UUID, sessionDirectoryName: String) {
        withContext(Dispatchers.IO) {
            val sessionDirectory = sessionsRootDirectory().resolve(sessionDirectoryName)
            val chunkFiles = sessionDirectory.listFiles { file ->
                file.isFile && file.name.startsWith("chunk_") && file.name.endsWith(".csv")
            }.orEmpty()
            if (chunkFiles.isEmpty()) {
                return@withContext
            }
            chunkFiles.forEach { file -> MotionCaptureChunkCompressor.gzipFile(file) }
            segmentDao.getBySessionId(sessionId).forEach { entity ->
                val record = entity.toRecord()
                val updatedNames = record.chunkFileNames.map { name ->
                    if (sessionDirectory.resolve("$name.gz").exists()) "$name.gz" else name
                }
                if (updatedNames != record.chunkFileNames) {
                    segmentDao.insert(record.copy(chunkFileNames = updatedNames).toEntity())
                }
            }
        }
    }

    private suspend fun abortCaptureForLowStorage(session: MotionCaptureSessionRecord) {
        if (lowStorageAbortTriggered) {
            return
        }
        lowStorageAbortTriggered = true
        Log.e(TAG, "Motion capture aborted - low storage (free=${sessionsRootDirectory().usableSpace} bytes)")
        writeEvent(
            MotionCaptureEventRecord(
                eventType = MotionCaptureEventType.CAPTURE_ABORTED_LOW_STORAGE,
                epochTimeMs = System.currentTimeMillis(),
                elapsedRealtimeNanos = SystemClock.elapsedRealtimeNanos(),
                notes = "freeBytes=${sessionsRootDirectory().usableSpace}"
            ),
            session.id
        )
        scope.launch { stopCapture(MotionCaptureSessionStatus.ABANDONED) }
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
        setupRepDetector(session)
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

    private fun notifyStillness(still: Boolean) {
        if (still == lastStillness) return
        lastStillness = still
        onStillnessChanged(still)
    }

    /**
     * Detected reps ride the capture stream so the ground-truth pair (actual vs detected) comes from
     * identical samples. LINEAR_ACCELERATION is preferred; otherwise ACC with an own gravity estimate.
     */
    private fun setupRepDetector(session: MotionCaptureSessionRecord) {
        val observed = session.sensorConfig.observedSensors
            ?: sensorRepository.observedSensors(session.sensorConfig)
        val useLinear = MotionSensorType.LINEAR_ACCELERATION in observed
        repDetectorSensor = if (useLinear) MotionSensorType.LINEAR_ACCELERATION else MotionSensorType.ACCELEROMETER
        repDetector = RepDetector(subtractGravity = !useLinear)
    }

    private suspend fun writeSample(sample: com.gabstra.myworkoutassistant.shared.motion.MotionSensorSample) {
        val session = activeSession ?: return
        if (sample.sensorType == repDetectorSensor) {
            repDetector?.addSample(sample.elapsedRealtimeNanos, sample.x, sample.y, sample.z)
            notifyStillness(stillnessTracker.addSample(sample.elapsedRealtimeNanos, sample.x, sample.y, sample.z))
        }
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
        elapsedRealtimeNanos: Long,
        previousWorkoutState: com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState?
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
                segmentId = previousSegment?.id,
                actualReps = completedSetReps(previousWorkoutState),
                detectedReps = repDetector?.reps
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

    /** Reps entered for the set that just completed; null for timed sets, skipped data, or non-set states. */
    private fun completedSetReps(state: WorkoutState?): Int? {
        val setData = (state as? WorkoutState.Set)?.currentSetData ?: return null
        return when (setData) {
            is WeightSetData -> setData.actualReps
            is BodyWeightSetData -> setData.actualReps
            else -> null
        }
    }

    private fun initializeEventsFile(sessionDirectory: File) {
        val eventsFile = sessionDirectory.resolve(eventsFileName)
        if (eventsFile.exists()) {
            return
        }
        eventsFile.writeText(
            "eventType,epochTimeMs,elapsedRealtimeNanos,stateName,exerciseId,exerciseName," +
                "setId,setIndex,exerciseType,noRepExpected,segmentId,reviewStatus,notes,actualReps\n"
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
                    csvValue(event.notes),
                    event.actualReps?.toString() ?: ""
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
        val sessionDirectory = sessionsRootDirectory().resolve(session.sessionDirectoryName).apply { mkdirs() }
        if (sessionDirectory.usableSpace < MIN_FREE_BYTES_FOR_CAPTURE) {
            abortCaptureForLowStorage(session)
            return
        }
        currentChunkIndex += 1
        currentChunkSampleCount = 0
        val chunkFileName = "chunk_${currentChunkIndex.toString().padStart(5, '0')}.csv"
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
            sensorConfigJson = MotionCaptureJson.sensorConfigToJson(this.sensorConfig),
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
