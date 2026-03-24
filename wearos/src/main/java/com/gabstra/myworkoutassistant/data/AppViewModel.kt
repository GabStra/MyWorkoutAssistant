package com.gabstra.myworkoutassistant.data

import android.content.Context
import androidx.core.content.edit
import android.widget.Toast
import androidx.compose.runtime.State
import androidx.compose.runtime.asIntState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import com.gabstra.myworkoutassistant.MyApplication
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.ExerciseInfo
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgression
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryStore
import com.gabstra.myworkoutassistant.shared.WorkoutPlan
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.findWorkoutForHistory
import com.gabstra.myworkoutassistant.shared.initializeSetData
import com.gabstra.myworkoutassistant.shared.workout.ui.WorkoutScreenState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import com.gabstra.myworkoutassistant.shared.workout.model.InterruptedWorkout
import com.gabstra.myworkoutassistant.shared.workout.model.SessionOwnerDevice
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.shared.datalayer.DataLayerPaths
import com.gabstra.myworkoutassistant.sync.PendingWorkoutHistorySyncTracker
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.Node
import com.google.android.gms.wearable.PutDataMapRequest
import com.google.android.gms.tasks.Tasks
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.time.LocalDateTime
import java.util.UUID
import com.gabstra.myworkoutassistant.data.checkConnection
import com.gabstra.myworkoutassistant.sync.WorkoutHistorySyncWorker
import com.gabstra.myworkoutassistant.shared.UNASSIGNED_PLAN_NAME
import com.gabstra.myworkoutassistant.shared.workout.recovery.CalibrationRecoveryChoice
import com.gabstra.myworkoutassistant.shared.workout.recovery.DecodedRecoveryRuntimeSnapshot
import com.gabstra.myworkoutassistant.shared.workout.recovery.RecoveryPromptUiState
import com.gabstra.myworkoutassistant.shared.workout.recovery.RecoveryResumeOptions
import com.gabstra.myworkoutassistant.shared.workout.recovery.RecoveryStateType
import com.gabstra.myworkoutassistant.shared.workout.recovery.TimerRecoveryChoice
import com.gabstra.myworkoutassistant.shared.workout.recovery.WorkoutRecoveryCheckpoint
import com.gabstra.myworkoutassistant.shared.workout.recovery.WorkoutRecoverySnapshotCodec

internal enum class WorkoutHistorySyncRequestMode {
    Debounced,
    Immediate
}

internal fun resolveWorkoutHistorySyncRequestMode(
    currentState: WorkoutState,
    isDone: Boolean
): WorkoutHistorySyncRequestMode? = when {
    isDone -> WorkoutHistorySyncRequestMode.Immediate
    currentState is WorkoutState.Set || currentState is WorkoutState.Rest ->
        WorkoutHistorySyncRequestMode.Debounced
    else -> null
}

open class AppViewModel : WorkoutViewModel() {

    companion object {
        private const val TAG = "AppViewModel"
        private const val WORKOUT_SYNC_LOG_TAG = "WorkoutSync"
        private const val SYNC_TIMEOUT_MS = 10_000L
    }

    private var applicationContext: android.content.Context? = null
    private var lastCheckpointFingerprint: String? = null
    private var forceSyncRecoveryWrite = false
    private var pendingPostRecoveryTimerReanchor = false
    private var pendingRecoveryCheckpoint: WorkoutRecoveryCheckpoint? = null
    private var pendingRecoveryResumeOptions: RecoveryResumeOptions = RecoveryResumeOptions()

    /** Pending sync: transactionId -> workoutHistoryId. Cleared on process death; those histories stay unsynced and retry at start. */
    private val pendingSyncTransactions = mutableMapOf<String, UUID>()

    fun initApplicationContext(context: android.content.Context) {
        applicationContext = context.applicationContext
        (context.applicationContext as? MyApplication)?.coroutineExceptionHandler?.let {
            coroutineExceptionHandler = it
        }
    }

    private fun checkpointStore(): WorkoutRecoveryCheckpointStore? {
        val context = applicationContext ?: return null
        return WorkoutRecoveryCheckpointStore(context)
    }

    private fun getPendingWorkoutHistoryIds(context: Context): Set<UUID> {
        return PendingWorkoutHistorySyncTracker.getPendingIds(context)
    }

    private fun enqueuePendingWorkoutHistoryId(context: Context, id: UUID) {
        PendingWorkoutHistorySyncTracker.enqueue(context, id)
    }

    private fun dequeuePendingWorkoutHistoryId(context: Context, id: UUID) {
        PendingWorkoutHistorySyncTracker.dequeue(context, id)
    }

    private fun retainPendingWorkoutHistoryIds(context: Context, validIds: Set<UUID>) {
        PendingWorkoutHistorySyncTracker.retain(context, validIds)
    }

    /** Call before sending a completed history so SYNC_COMPLETE can clear it from the pending queue. */
    private fun registerPendingSyncTransaction(transactionId: String, workoutHistoryId: UUID) {
        pendingSyncTransactions[transactionId] = workoutHistoryId
    }

    /** Called when SYNC_COMPLETE broadcast is received; clears the corresponding pending outbound history. */
    fun markHistorySyncedForTransaction(transactionId: String?) {
        if (transactionId == null) return
        val historyId = pendingSyncTransactions.remove(transactionId) ?: return
        val ctx = applicationContext ?: return
        dequeuePendingWorkoutHistoryId(ctx, historyId)
        Log.d("AppViewModel", "Cleared pending workout history $historyId for transaction $transactionId")
    }
    
    private var dataClient: DataClient? = null
    var phoneNode by mutableStateOf<Node?>(null)
    
    // Mutex to serialize sync operations and prevent interleaving DataItems
    private val syncMutex = Mutex()

    // Debouncer for batching rapid sync operations
    private val syncDebouncer = WearOSSyncDebouncer(viewModelScope, debounceDelayMs = 5000L)

    val isPhoneConnectedAndHasApp: Boolean
        get() = phoneNode != null

    fun initDataClient(client: DataClient) {
        dataClient = client
    }

    private val _executeStartWorkout = mutableStateOf<UUID?>(null)
    val executeStartWorkout: State<UUID?> = _executeStartWorkout

    // Method to trigger the action
    fun triggerStartWorkout(globalId: UUID) {
        _executeStartWorkout.value = globalId
    }

    // Method to reset/consume the action
    fun consumeStartWorkout() {
        _executeStartWorkout.value = null
    }

    private val _showRecoveryPrompt = mutableStateOf(false)
    val showRecoveryPrompt: State<Boolean> = _showRecoveryPrompt

    private val _recoveryWorkout = mutableStateOf<InterruptedWorkout?>(null)
    val recoveryWorkout: State<InterruptedWorkout?> = _recoveryWorkout
    private val _recoveryPromptUiState = mutableStateOf(RecoveryPromptUiState())
    internal val recoveryPromptUiState: State<RecoveryPromptUiState> = _recoveryPromptUiState

    private val _showRecoveredWorkoutNotice = mutableStateOf(false)
    val showRecoveredWorkoutNotice: State<Boolean> = _showRecoveredWorkoutNotice
    private var skipNextResumeLastState = false

    fun consumeRecoveredWorkoutNotice() {
        _showRecoveredWorkoutNotice.value = false
    }

    fun consumeSkipNextResumeLastState(): Boolean {
        val shouldSkip = skipNextResumeLastState
        skipNextResumeLastState = false
        return shouldSkip
    }

    internal fun showRecoveryPrompt(
        interruptedWorkout: InterruptedWorkout,
        checkpoint: WorkoutRecoveryCheckpoint?
    ) {
        val showCalibrationOptions = checkpoint?.isCalibrationSetExecution == true ||
            checkpoint?.stateType == RecoveryStateType.CALIBRATION_LOAD ||
            checkpoint?.stateType == RecoveryStateType.CALIBRATION_RIR ||
            checkpoint?.stateType == RecoveryStateType.AUTO_REGULATION_RIR
        val showTimerOptions = !showCalibrationOptions && shouldShowTimerOptions(checkpoint, interruptedWorkout.workoutId)
        val exerciseName = resolveRecoveryExerciseName(interruptedWorkout, checkpoint)

        _recoveryPromptUiState.value = RecoveryPromptUiState(
            workoutName = interruptedWorkout.workoutName,
            exerciseName = exerciseName.orEmpty(),
            workoutStartTime = interruptedWorkout.workoutHistory.startTime,
            showTimerOptions = showTimerOptions,
            showCalibrationOptions = showCalibrationOptions
        )
        _recoveryWorkout.value = interruptedWorkout
        _showRecoveryPrompt.value = true
        pendingRecoveryCheckpoint = checkpoint
    }

    fun hideRecoveryPrompt() {
        _showRecoveryPrompt.value = false
        _recoveryWorkout.value = null
        _recoveryPromptUiState.value = RecoveryPromptUiState()
    }

    internal fun setPendingRecoveryResumeOptions(options: RecoveryResumeOptions) {
        pendingRecoveryResumeOptions = options
    }

    override fun prepareResumeWorkout(workoutId: UUID, workoutHistoryId: UUID) {
        super.prepareResumeWorkout(workoutId, workoutHistoryId)
        clearRecoveryPromptState()
    }

    fun prepareResumeWorkout(interruptedWorkout: InterruptedWorkout) {
        prepareResumeWorkout(interruptedWorkout.workoutId, interruptedWorkout.workoutHistory.id)
    }

    private fun clearRecoveryPromptState() {
        _recoveryWorkout.value = null
        _recoveryPromptUiState.value = RecoveryPromptUiState()
        pendingRecoveryCheckpoint = null
        pendingRecoveryResumeOptions = RecoveryResumeOptions()
    }

    internal fun getSavedRecoveryCheckpoint(): WorkoutRecoveryCheckpoint? {
        return checkpointStore()?.load()
    }

    fun clearRecoveryCheckpoint() {
        checkpointStore()?.clear()
        lastCheckpointFingerprint = null
        clearRecoveryPromptState()
    }

    private fun shouldShowTimerOptions(
        checkpoint: WorkoutRecoveryCheckpoint?,
        workoutId: UUID
    ): Boolean {
        if (checkpoint == null || checkpoint.workoutId != workoutId) return false
        val timerEligibleState =
            checkpoint.stateType == RecoveryStateType.SET || checkpoint.stateType == RecoveryStateType.REST
        if (!timerEligibleState) return false
        if (checkpoint.isCalibrationSetExecution) return false

        val targetExercise = findExerciseForCheckpoint(checkpoint, workoutId) ?: return false
        val targetSet = checkpoint.setId?.let { setId ->
            targetExercise.sets.firstOrNull { it.id == setId }
        } ?: checkpoint.setIndex?.toInt()?.let { setIndex ->
            targetExercise.sets.getOrNull(setIndex)
        } ?: return false

        return targetSet is TimedDurationSet || targetSet is EnduranceSet || targetSet is RestSet
    }

    private fun resolveRecoveryExerciseName(
        interruptedWorkout: InterruptedWorkout,
        checkpoint: WorkoutRecoveryCheckpoint?
    ): String? {
        return checkpoint
            ?.takeIf { it.workoutId == interruptedWorkout.workoutId }
            ?.let { findExerciseForCheckpoint(it, interruptedWorkout.workoutId)?.name }
    }

    private fun findExerciseForCheckpoint(
        checkpoint: WorkoutRecoveryCheckpoint,
        workoutId: UUID
    ): Exercise? {
        val workout = workoutStore.workouts.firstOrNull { it.id == workoutId } ?: return null
        val exercises = workout.workoutComponents.filterIsInstance<Exercise>() +
            workout.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }

        return checkpoint.exerciseId?.let { exerciseId ->
            exercises.firstOrNull { it.id == exerciseId }
        } ?: exercises.firstOrNull()
    }

    fun persistRecoverySnapshotNow(synchronous: Boolean = false) {
        forceSyncRecoveryWrite = synchronous
        try {
            rebuildScreenState()
        } finally {
            forceSyncRecoveryWrite = false
        }
    }

    fun clearWorkoutInProgressFlag() {
        val context = applicationContext ?: return
        val prefs = context.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
        prefs.edit { putBoolean("isWorkoutInProgress", false) }
    }

    /**
     * Discards an interrupted workout: deletes the workout record and persisted interrupted history
     * locally, then notifies mobile to mirror the deletion.
     */
    fun discardInterruptedWorkout(interruptedWorkout: InterruptedWorkout) {
        launchIO {
            setHistoryDao.deleteByWorkoutHistoryId(interruptedWorkout.workoutHistory.id)
            restHistoryDao.deleteByWorkoutHistoryId(interruptedWorkout.workoutHistory.id)
            workoutRecordDao.deleteByWorkoutId(interruptedWorkout.workoutId)
            workoutHistoryDao.deleteById(interruptedWorkout.workoutHistory.id)
            sendDiscardInterruptedWorkoutToPhone(
                workoutId = interruptedWorkout.workoutId,
                workoutHistoryId = interruptedWorkout.workoutHistory.id
            )
        }
    }

    private suspend fun sendDiscardInterruptedWorkoutToPhone(
        workoutId: UUID,
        workoutHistoryId: UUID
    ) {
        val client = dataClient ?: run {
            Log.w("WorkoutSync", "Discard sync skipped: dataClient not initialized")
            return
        }
        val transactionId = UUID.randomUUID().toString()
        val path = DataLayerPaths.buildPath(DataLayerPaths.WORKOUT_HISTORY_DISCARD_PREFIX, transactionId)
        val request = PutDataMapRequest.create(path).apply {
            dataMap.putString("transactionId", transactionId)
            dataMap.putString("workoutId", workoutId.toString())
            dataMap.putString("workoutHistoryId", workoutHistoryId.toString())
            dataMap.putString("timestamp", System.currentTimeMillis().toString())
        }.asPutDataRequest().setUrgent()

        runCatching {
            Tasks.await(client.putDataItem(request))
            Log.d(
                "WorkoutSync",
                "Sent workout discard event tx=$transactionId workoutId=$workoutId workoutHistoryId=$workoutHistoryId"
            )
        }.onFailure { exception ->
            Log.e(
                "WorkoutSync",
                "Failed to send workout discard event tx=$transactionId workoutId=$workoutId workoutHistoryId=$workoutHistoryId",
                exception
            )
        }
    }

    private val _hrDisplayMode = mutableStateOf(0)
    val hrDisplayMode: State<Int> = _hrDisplayMode.asIntState()
    private val _headerDisplayMode = mutableStateOf(0)
    val headerDisplayMode: State<Int> = _headerDisplayMode.asIntState()
    private val _isRestTimerPageVisible = mutableStateOf(true)
    val isRestTimerPageVisible: State<Boolean> = _isRestTimerPageVisible
    private val _isExerciseDetailPageVisible = mutableStateOf(true)
    val isExerciseDetailPageVisible: State<Boolean> = _isExerciseDetailPageVisible

    private val _isSyncingToPhone = mutableStateOf(false)
    val isSyncingToPhone: State<Boolean> = _isSyncingToPhone

    enum class SyncStatus {
        Idle,
        Syncing,
        Success,
        Failure
    }

    private val _syncStatus = MutableStateFlow(SyncStatus.Idle)
    val syncStatus: StateFlow<SyncStatus> = _syncStatus.asStateFlow()

    private val _hasPendingWorkoutSync = mutableStateOf(false)
    val hasPendingWorkoutSync: State<Boolean> = _hasPendingWorkoutSync

    private var pendingSyncAfterReconnect = false
    private var pendingSyncContext: Context? = null
    
    // Timeout jobs for sync state cleanup
    private var isSyncingToPhoneTimeoutJob: Job? = null
    private var syncStatusTimeoutJob: Job? = null
    
    /**
     * Starts a timeout coroutine that resets _isSyncingToPhone after 10 seconds if still syncing.
     */
    private fun startIsSyncingToPhoneTimeout() {
        isSyncingToPhoneTimeoutJob?.cancel()
        isSyncingToPhoneTimeoutJob = launchDefault {
            delay(SYNC_TIMEOUT_MS)
            if (_isSyncingToPhone.value) {
                _isSyncingToPhone.value = false
                Log.w(TAG, "Sync timeout: resetting _isSyncingToPhone after $SYNC_TIMEOUT_MS ms")
            }
        }
    }
    
    /**
     * Starts a timeout coroutine that resets _syncStatus after 10 seconds if still syncing.
     */
    private fun startSyncStatusTimeout() {
        syncStatusTimeoutJob?.cancel()
        syncStatusTimeoutJob = launchDefault {
            delay(SYNC_TIMEOUT_MS)
            if (_syncStatus.value == SyncStatus.Syncing) {
                _syncStatus.value = SyncStatus.Idle
                Log.w(TAG, "Sync timeout: resetting _syncStatus after $SYNC_TIMEOUT_MS ms")
            }
        }
    }
    
    /**
     * Cancels timeout jobs when sync completes.
     */
    private fun cancelSyncTimeouts() {
        isSyncingToPhoneTimeoutJob?.cancel()
        isSyncingToPhoneTimeoutJob = null
        syncStatusTimeoutJob?.cancel()
        syncStatusTimeoutJob = null
    }

    fun switchHrDisplayMode() {
        _hrDisplayMode.value = (_hrDisplayMode.value + 1) % 2
        rebuildScreenState()
    }

    fun switchHeaderDisplayMode() {
        _headerDisplayMode.value = (_headerDisplayMode.value + 1) % 2
        rebuildScreenState()
    }

    fun setRestTimerPageVisibility(isVisible: Boolean) {
        if (_isRestTimerPageVisible.value == isVisible) return
        _isRestTimerPageVisible.value = isVisible
        rebuildScreenState()
    }

    fun setExerciseDetailPageVisibility(isVisible: Boolean) {
        if (_isExerciseDetailPageVisible.value == isVisible) return
        _isExerciseDetailPageVisible.value = isVisible
        rebuildScreenState()
    }

    fun onPhoneConnectionChanged(isConnected: Boolean) {
        if (!isConnected || !pendingSyncAfterReconnect) return
        pendingSyncAfterReconnect = false
        val context = pendingSyncContext
        pendingSyncContext = null
        requestWorkoutHistorySync(context)
    }

    override fun rebuildScreenState() {
        val newState = WorkoutScreenState(
            workoutState = workoutState.value,
            sessionPhase = sessionPhase.value,
            nextWorkoutState = nextWorkoutState.value,
            selectedWorkout = selectedWorkout.value,
            isPaused = isPaused.value,
            hasWorkoutRecord = hasWorkoutRecord.value,
            isResuming = isResuming.value,
            isRefreshing = isRefreshing.value,
            isCustomDialogOpen = isCustomDialogOpen.value,
            enableWorkoutNotificationFlow = enableWorkoutNotificationFlow.value,
            userAge = userAge.value,
            measuredMaxHeartRate = workoutStore.measuredMaxHeartRate,
            restingHeartRate = workoutStore.restingHeartRate,
            startWorkoutTime = startWorkoutTime,
            enableDimming = enableDimming.value,
            keepScreenOn = keepScreenOn.value,
            currentScreenDimmingState = currentScreenDimmingState.value,
            headerDisplayMode = headerDisplayMode.value,
            hrDisplayMode = hrDisplayMode.value,
            isRestTimerPageVisible = isRestTimerPageVisible.value,
            isExerciseDetailPageVisible = isExerciseDetailPageVisible.value,
        )
        
        // Only emit if state actually changed
        if (_screenState.value != newState) {
            _screenState.value = newState
        }

        persistRecoveryCheckpointForCurrentState(newState)
    }

    private fun persistRecoveryCheckpointForCurrentState(screenState: WorkoutScreenState) {
        val context = applicationContext ?: return
        val selectedWorkoutId = selectedWorkout.value.id

        // Clear checkpoint only when workout is completed. Use synchronous write so the clear
        // is durable before process death (e.g. user leaves immediately after completion).
        if (screenState.workoutState is WorkoutState.Completed) {
            checkpointStore()?.clear(synchronous = true)
            lastCheckpointFingerprint = null
            return
        }

        if (screenState.sessionPhase != com.gabstra.myworkoutassistant.shared.workout.ui.WorkoutSessionPhase.ACTIVE) {
            val isWorkoutInProgress = context
                .getSharedPreferences("workout_state", Context.MODE_PRIVATE)
                .getBoolean("isWorkoutInProgress", false)
            if (!isWorkoutInProgress) {
                checkpointStore()?.clear()
                lastCheckpointFingerprint = null
            }
            return
        }

        val currentState = screenState.workoutState
        val stateType = when (currentState) {
            is WorkoutState.Set -> RecoveryStateType.SET
            is WorkoutState.Rest -> RecoveryStateType.REST
            is WorkoutState.CalibrationLoadSelection -> RecoveryStateType.CALIBRATION_LOAD
            is WorkoutState.CalibrationRIRSelection -> RecoveryStateType.CALIBRATION_RIR
            is WorkoutState.AutoRegulationRIRSelection -> RecoveryStateType.AUTO_REGULATION_RIR
            else -> RecoveryStateType.UNKNOWN
        }

        if (stateType == RecoveryStateType.UNKNOWN) {
            return
        }

        val exerciseId = when (currentState) {
            is WorkoutState.Set -> currentState.exerciseId
            is WorkoutState.Rest -> currentState.exerciseId
            is WorkoutState.CalibrationLoadSelection -> currentState.exerciseId
            is WorkoutState.CalibrationRIRSelection -> currentState.exerciseId
            is WorkoutState.AutoRegulationRIRSelection -> currentState.exerciseId
            else -> null
        }

        val setId = when (currentState) {
            is WorkoutState.Set -> currentState.set.id
            is WorkoutState.Rest -> currentState.set.id
            is WorkoutState.CalibrationLoadSelection -> currentState.calibrationSet.id
            is WorkoutState.CalibrationRIRSelection -> currentState.calibrationSet.id
            is WorkoutState.AutoRegulationRIRSelection -> currentState.workSet.id
            else -> null
        }

        val setIndex = when (currentState) {
            is WorkoutState.Set -> currentState.setIndex
            is WorkoutState.CalibrationLoadSelection -> currentState.setIndex
            is WorkoutState.CalibrationRIRSelection -> currentState.setIndex
            is WorkoutState.AutoRegulationRIRSelection -> currentState.setIndex
            else -> null
        }

        val restOrder = (currentState as? WorkoutState.Rest)?.order
        var setStartEpochMs = (currentState as? WorkoutState.Set)?.startTime?.let(::toEpochMillis)
        if (stateType == RecoveryStateType.SET && setStartEpochMs == null) {
            val existingCheckpoint = checkpointStore()?.load()
            if (
                existingCheckpoint?.workoutId == selectedWorkoutId &&
                existingCheckpoint.stateType == RecoveryStateType.SET &&
                existingCheckpoint.exerciseId == exerciseId &&
                existingCheckpoint.setId == setId &&
                existingCheckpoint.setStartEpochMs != null
            ) {
                setStartEpochMs = existingCheckpoint.setStartEpochMs
            }
        }

        val checkpoint = WorkoutRecoveryCheckpoint(
            workoutId = selectedWorkoutId,
            workoutHistoryId = currentWorkoutHistory?.id,
            stateType = stateType,
            isCalibrationSetExecution = (currentState as? WorkoutState.Set)?.isCalibrationSet == true,
            exerciseId = exerciseId,
            setId = setId,
            setIndex = setIndex,
            restOrder = restOrder,
            setStartEpochMs = setStartEpochMs,
            updatedAtEpochMs = System.currentTimeMillis()
        )

        val checkpointStore = WorkoutRecoveryCheckpointStore(context)
        val runtimeSnapshot = exportRecoveryStateMachine()?.let { (sequence, currentIndex) ->
            val runtimeSnapshotJson = WorkoutRecoverySnapshotCodec.encode(
                workoutId = selectedWorkoutId,
                workoutHistoryId = currentWorkoutHistory?.id,
                currentIndex = currentIndex,
                sequenceItems = sequence
            )
            currentIndex to runtimeSnapshotJson
        }
        val timerProgress = getTimerProgressKey(currentState)
        val sequenceIndex = runtimeSnapshot?.first ?: -1
        val isTimerActivelyRunning = when (currentState) {
            is WorkoutState.Set -> currentState.startTime != null &&
                (
                    currentState.currentSetData is TimedDurationSetData ||
                        currentState.currentSetData is EnduranceSetData
                    )
            is WorkoutState.Rest -> currentState.startTime != null
            else -> false
        }
        val shouldWriteSynchronously = forceSyncRecoveryWrite || isTimerActivelyRunning
        val fingerprint =
            "${checkpoint.workoutId}:${checkpoint.stateType}:${checkpoint.exerciseId}:${checkpoint.setId}:${checkpoint.setIndex}:${checkpoint.restOrder}:${checkpoint.setStartEpochMs}:$sequenceIndex:$timerProgress"

        if (fingerprint != lastCheckpointFingerprint) {
            checkpointStore.save(checkpoint, synchronous = shouldWriteSynchronously)
            lastCheckpointFingerprint = fingerprint
        }

        runtimeSnapshot?.second?.let { runtimeSnapshotJson ->
            checkpointStore.saveRuntimeSnapshotJson(
                snapshotJson = runtimeSnapshotJson,
                synchronous = shouldWriteSynchronously
            )
        }
    }

    private fun getTimerProgressKey(state: WorkoutState): Int {
        return when (state) {
            is WorkoutState.Set -> when (val setData = state.currentSetData) {
                is TimedDurationSetData -> setData.endTimer
                is EnduranceSetData -> setData.endTimer
                else -> -1
            }
            is WorkoutState.Rest -> {
                (state.currentSetData as? RestSetData)?.endTimer ?: -1
            }
            else -> -1
        }
    }

    fun sendAll(context: Context) {
        launchMain {
            try {
                withContext(Dispatchers.IO) {
                    val statuses = mutableListOf<Boolean>()
                    val workouts = workoutStore.workouts.filter { it.enabled && it.isActive }

                    if (workouts.isEmpty()) return@withContext

                    workouts.forEach {
                        try {
                            val workoutHistory = workoutHistoryDao.getLatestWorkoutHistoryByWorkoutId(it.id)
                                ?: return@forEach
                            val setHistories =
                                setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)
                            val exercises = it.workoutComponents.filterIsInstance<Exercise>() + it.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }
                            val exerciseInfos = exercises.mapNotNull { exercise ->
                                getExerciseInfoDao().getExerciseInfoById(exercise.id)
                            }

                            val workoutRecord = workoutRecordDao.getWorkoutRecordByWorkoutId(it.id)
                            val exerciseSessionProgressions = exerciseSessionProgressionDao.getByWorkoutHistoryId(workoutHistory.id)

                            val errorLogs = try {
                                (context.applicationContext as? MyApplication)?.getErrorLogs() ?: emptyList()
                            } catch (e: Exception) {
                                Log.e(TAG, "Error getting error logs", e)
                                emptyList()
                            }

                            val (success, _) = syncMutex.withLock {
                                sendWorkoutHistoryStore(
                                    dataClient!!,
                                    WorkoutHistoryStore(
                                        WorkoutHistory = workoutHistory,
                                        SetHistories = setHistories,
                                        ExerciseInfos = exerciseInfos,
                                        WorkoutRecord = workoutRecord,
                                        ExerciseSessionProgressions = exerciseSessionProgressions,
                                        ErrorLogs = errorLogs,
                                        RestHistories = restHistoryDao.getByWorkoutHistoryIdOrdered(workoutHistory.id)
                                    ),
                                    context
                                )
                            }
                            
                            // Clear error logs after successful send
                            if (success && errorLogs.isNotEmpty()) {
                                try {
                                    (context.applicationContext as? MyApplication)?.clearErrorLogs()
                                } catch (e: Exception) {
                                    Log.e(TAG, "Error clearing error logs", e)
                                }
                            }
                            
                            statuses.add(success)
                        } catch (e: Exception) {
                            Log.e(TAG, "Error sending workout data for ${it.id}", e)
                            statuses.add(false)
                            Log.d(TAG, "Detailed sync error: ${e.message}")
                            withContext(Dispatchers.Main) {
                                showSyncFailedToastIfInactive(context)
                            }
                        }
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Error in sendAll", e)
                Log.d(TAG, "Detailed sync error: ${e.message}")
                withContext(Dispatchers.Main) {
                    showSyncFailedToastIfInactive(context)
                }
            }
        }
    }

    /**
     * Re-sends only completed workout histories that were produced on Wear and are still pending
     * confirmation from the phone.
     */
    fun sendUnsyncedHistories(context: Context) {
        launchMain {
            try {
                withContext(Dispatchers.IO) {
                    val client = dataClient ?: return@withContext
                    val pendingIds = getPendingWorkoutHistoryIds(context)
                    if (pendingIds.isEmpty()) return@withContext

                    val allCompleted = workoutHistoryDao.getAllWorkoutHistoriesByIsDone(true)
                    val validPendingIds = allCompleted.map { it.id }.toSet().intersect(pendingIds)
                    retainPendingWorkoutHistoryIds(context, validPendingIds)
                    if (validPendingIds.isEmpty()) return@withContext

                    val unsynced = allCompleted.filter { it.id in validPendingIds }
                    if (unsynced.isEmpty()) return@withContext

                    Log.d(
                        "DataLayerSync",
                        "sendUnsyncedHistories: re-sending ${unsynced.size} pending Wear history item(s)"
                    )
                    unsynced.forEachIndexed { index, workoutHistory ->
                        try {
                            Log.d(
                                "DataLayerSync",
                                "Sending pending Wear history id=${workoutHistory.id} (${index + 1} of ${unsynced.size})"
                            )
                            val workout = workoutStore.findWorkoutForHistory(workoutHistory)
                                ?: return@forEachIndexed
                            val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)
                            val exerciseInfos = loadExerciseInfos(workout)
                            val workoutRecord = workoutRecordDao.getWorkoutRecordByWorkoutId(workout.id)
                            val exerciseSessionProgressions = exerciseSessionProgressionDao.getByWorkoutHistoryId(workoutHistory.id)
                            val errorLogs = try {
                                (context.applicationContext as? MyApplication)?.getErrorLogs() ?: emptyList()
                            } catch (e: Exception) {
                                Log.e(TAG, "Error getting error logs", e)
                                emptyList()
                            }

                            val transactionId = UUID.randomUUID().toString()
                            registerPendingSyncTransaction(transactionId, workoutHistory.id)
                            val (success, _) = syncMutex.withLock {
                                sendWorkoutHistoryStore(
                                    client,
                                    WorkoutHistoryStore(
                                        WorkoutHistory = workoutHistory,
                                        SetHistories = setHistories,
                                        ExerciseInfos = exerciseInfos,
                                        WorkoutRecord = workoutRecord,
                                        ExerciseSessionProgressions = exerciseSessionProgressions,
                                        ErrorLogs = errorLogs,
                                        RestHistories = restHistoryDao.getByWorkoutHistoryIdOrdered(workoutHistory.id)
                                    ),
                                    context,
                                    transactionId
                                )
                            }
                            if (success) {
                                dequeuePendingWorkoutHistoryId(context, workoutHistory.id)
                            }
                            if (success && errorLogs.isNotEmpty()) {
                                try {
                                    (context.applicationContext as? MyApplication)?.clearErrorLogs()
                                } catch (e: Exception) {
                                    Log.e(TAG, "Error clearing error logs", e)
                                }
                            }
                        } catch (e: Exception) {
                            Log.e(TAG, "Error sending unsynced history ${workoutHistory.id}", e)
                        }
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Error in sendUnsyncedHistories", e)
            }
        }
    }

    fun sendWorkoutHistoryToPhone(context: Context, onEnd: (Boolean) -> Unit = {}) {
        launchIO {
            try {
                if (!checkConnection(context)) {
                    withContext(Dispatchers.Main) {
                        handleMissingPhoneConnection(context, onEnd)
                    }
                    return@launchIO
                }

                withContext(Dispatchers.Main) {
                    beginPhoneSync()
                }

                val workoutHistory = resolveWorkoutHistoryForSync()

                if (workoutHistory == null) {
                    withContext(Dispatchers.Main) {
                        finishPhoneSync(success = false, onEnd = onEnd)
                    }
                    return@launchIO
                }

                val workoutHistoryStore = buildWorkoutHistoryStoreForSelectedWorkout(workoutHistory)
                val transactionId = createSyncTransactionIdIfNeeded(workoutHistory)
                val (success, _) = dataClient?.let {
                    syncMutex.withLock {
                        sendWorkoutHistoryStore(
                            it,
                            workoutHistoryStore,
                            context,
                            transactionId
                        )
                    }
                } ?: Pair(false, "")

                if (success && workoutHistory.isDone) {
                    dequeuePendingWorkoutHistoryId(context, workoutHistory.id)
                }

                withContext(Dispatchers.Main) {
                    finishPhoneSync(success = success, onEnd = onEnd)
                }
            } catch (e: Exception) {
                Log.e(TAG, "Error sending workout history to phone", e)
                withContext(NonCancellable + Dispatchers.Main) {
                    Log.d(TAG, "Detailed sync error: ${e.message}")
                    finishPhoneSync(success = false, onEnd = onEnd)
                }
            }
        }
    }

    private fun beginPhoneSync() {
        _isSyncingToPhone.value = true
        startIsSyncingToPhoneTimeout()
    }

    private fun finishPhoneSync(success: Boolean, onEnd: (Boolean) -> Unit) {
        _isSyncingToPhone.value = false
        cancelSyncTimeouts()
        onEnd(success)
    }

    private fun handleMissingPhoneConnection(context: Context, onEnd: (Boolean) -> Unit) {
        if (!isWorkoutActive()) {
            // Toast disabled: "Connect your phone to sync."
            // Toast.makeText(context, "Connect your phone to sync.", Toast.LENGTH_SHORT).show()
        }
        onEnd(false)
    }

    private suspend fun resolveWorkoutHistoryForSync(): com.gabstra.myworkoutassistant.shared.WorkoutHistory? {
        val selectedWorkoutId = selectedWorkout.value.id
        val persistedCurrentHistory = currentWorkoutHistory?.id?.let { workoutHistoryDao.getWorkoutHistoryById(it) }
        val latestUnfinishedHistory = workoutHistoryDao.getLatestWorkoutHistoryByWorkoutId(
            selectedWorkoutId,
            isDone = false
        )
        val latestCompletedHistory = workoutHistoryDao.getLatestWorkoutHistoryByWorkoutId(
            selectedWorkoutId,
            isDone = true
        )

        return if (workoutState.value is WorkoutState.Completed) {
            latestCompletedHistory ?: persistedCurrentHistory ?: latestUnfinishedHistory
        } else {
            persistedCurrentHistory ?: latestUnfinishedHistory ?: latestCompletedHistory
        }
    }

    private suspend fun buildWorkoutHistoryStoreForSelectedWorkout(
        workoutHistory: com.gabstra.myworkoutassistant.shared.WorkoutHistory
    ): WorkoutHistoryStore {
        val selectedWorkoutSnapshot = selectedWorkout.value
        return WorkoutHistoryStore(
            WorkoutHistory = workoutHistory,
            SetHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id),
            ExerciseInfos = loadExerciseInfos(selectedWorkoutSnapshot),
            WorkoutRecord = workoutRecordDao.getWorkoutRecordByWorkoutId(selectedWorkoutSnapshot.id),
            ExerciseSessionProgressions = exerciseSessionProgressionDao.getByWorkoutHistoryId(workoutHistory.id),
            RestHistories = restHistoryDao.getByWorkoutHistoryIdOrdered(workoutHistory.id)
        )
    }

    private suspend fun loadExerciseInfos(workout: com.gabstra.myworkoutassistant.shared.Workout): List<ExerciseInfo> {
        val exercises = workout.workoutComponents.filterIsInstance<Exercise>() +
            workout.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }
        return exercises.mapNotNull { getExerciseInfoDao().getExerciseInfoById(it.id) }
    }

    private fun createSyncTransactionIdIfNeeded(
        workoutHistory: com.gabstra.myworkoutassistant.shared.WorkoutHistory
    ): String? {
        if (!workoutHistory.isDone) return null
        return UUID.randomUUID().toString().also { registerPendingSyncTransaction(it, workoutHistory.id) }
    }

    private fun showSyncFailedToastIfInactive(context: Context) {
        if (!isWorkoutActive()) {
            // Toast disabled: "Couldn't sync with your phone. Try again."
            // Toast.makeText(context, "Couldn't sync with your phone. Try again.", Toast.LENGTH_LONG).show()
        }
    }

    private fun showSyncRetryingToastIfInactive(context: Context) {
        if (!isWorkoutActive()) {
            // Toast disabled: "Sync is retrying in background."
            // Toast.makeText(context, "Sync is retrying in background.", Toast.LENGTH_SHORT).show()
        }
    }

    override fun startWorkout() {
        _headerDisplayMode.value = 0
        _hrDisplayMode.value = 0
        _isRestTimerPageVisible.value = true
        super.startWorkout()
    }

    override fun goToNextState() {
        stopActiveTimerForCurrentState()
        super.goToNextState()
        restartCurrentRestStateForManualNavigation()
        reEvaluateDimmingForCurrentState()
    }

    /**
     * Wear-specific navigation entrypoint that ensures active timer services are not left running
     * when navigating backward to a previous set.
     */
    fun goToPreviousSetWear() {
        stopActiveTimerForCurrentState()
        goToPreviousSet()
        restartCurrentRestStateForManualNavigation()
        reEvaluateDimmingForCurrentState()
    }

    /**
     * Wear-specific navigation entrypoint that ensures active timer services are not left running
     * when navigating backward across non-rest states.
     */
    fun goToPreviousNonRestStateWear() {
        stopActiveTimerForCurrentState()
        goToPreviousNonRestState()
        restartCurrentRestStateForManualNavigation()
        reEvaluateDimmingForCurrentState()
    }

    private fun stopActiveTimerForCurrentState() {
        when (val currentState = workoutState.value) {
            is WorkoutState.Set -> {
                if (currentState.set is TimedDurationSet || currentState.set is EnduranceSet) {
                    workoutTimerService.unregisterTimer(currentState.set.id)
                    currentState.startTime = null
                }
            }

            is WorkoutState.Rest -> {
                workoutTimerService.unregisterTimer(currentState.set.id)
                currentState.startTime = null
            }

            else -> Unit
        }
    }

    private fun restartCurrentRestStateForManualNavigation() {
        val currentState = workoutState.value as? WorkoutState.Rest ?: return
        val originalSetData = currentState.currentSetData as? RestSetData ?: return
        val setData = normalizeRestTimerBounds(originalSetData)
        if (setData != originalSetData) {
            currentState.currentSetData = setData
        }
        if (setData.endTimer == setData.startTimer && currentState.startTime == null) return

        workoutTimerService.unregisterTimer(currentState.set.id)
        currentState.currentSetData = setData.copy(endTimer = setData.startTimer)
        currentState.startTime = null
    }

    /**
     * Wear OS layer on top of shared resume: loads checkpoint and runtime snapshot from platform
     * store, then runs shared [resumeWorkoutFromRecord]. In [onEnd], applies recovery (restore
     * state machine from snapshot or move to checkpoint state, timer/calibration options).
     */
    override fun resumeWorkoutFromRecord(onEnd: suspend () -> Unit) {
        _headerDisplayMode.value = 0
        _hrDisplayMode.value = 0
        _isRestTimerPageVisible.value = true
        skipNextResumeLastState = false
        val checkpoint = pendingRecoveryCheckpoint ?: getSavedRecoveryCheckpoint()
        val runtimeSnapshot = checkpointStore()
            ?.loadRuntimeSnapshotJson()
            ?.let { WorkoutRecoverySnapshotCodec.decode(it) }
        val recoveryOptions = pendingRecoveryResumeOptions

        super.resumeWorkoutFromRecord {
            applyRecoveryFromCheckpoint(
                checkpoint = checkpoint,
                runtimeSnapshot = runtimeSnapshot,
                recoveryOptions = recoveryOptions,
                onEnd = onEnd
            )
        }
    }

    /**
     * Applies process-death recovery after shared resume: restores state machine from [runtimeSnapshot]
     * or moves to [checkpoint] state, then applies [recoveryOptions] (timer continue/restart, calibration).
     */
    private suspend fun applyRecoveryFromCheckpoint(
        checkpoint: WorkoutRecoveryCheckpoint?,
        runtimeSnapshot: DecodedRecoveryRuntimeSnapshot?,
        recoveryOptions: RecoveryResumeOptions,
        onEnd: suspend () -> Unit
    ) {
        val selectedWorkoutId = selectedWorkout.value.id
        val shouldRestartCalibration = checkpoint != null &&
            checkpoint.workoutId == selectedWorkoutId &&
            recoveryOptions.calibrationChoice == CalibrationRecoveryChoice.RESTART &&
            (
                checkpoint.stateType == RecoveryStateType.CALIBRATION_LOAD ||
                    checkpoint.stateType == RecoveryStateType.CALIBRATION_RIR ||
                    checkpoint.isCalibrationSetExecution
                )

        var recoveryApplied = false

        if (!shouldRestartCalibration &&
            runtimeSnapshot != null &&
            runtimeSnapshot.workoutId == selectedWorkoutId
        ) {
            recoveryApplied = restoreRecoveryStateMachine(
                sequence = runtimeSnapshot.sequenceItems,
                currentIndex = runtimeSnapshot.currentIndex
            )
        }

        if (!recoveryApplied && checkpoint != null && checkpoint.workoutId == selectedWorkoutId) {
            val targetStateType = if (shouldRestartCalibration) {
                RecoveryStateType.CALIBRATION_LOAD.name
            } else {
                checkpoint.stateType.name
            }
            recoveryApplied = moveToRecoveredState(
                stateType = targetStateType,
                exerciseId = checkpoint.exerciseId,
                setId = checkpoint.setId,
                setIndex = checkpoint.setIndex,
                restOrder = checkpoint.restOrder
            )
        }

        if (recoveryApplied && checkpoint != null && checkpoint.workoutId == selectedWorkoutId) {
            val stateAligned = doesCurrentStateMatchCheckpointType(checkpoint)
            if (!stateAligned) {
                recoveryApplied = moveToRecoveredState(
                    stateType = checkpoint.stateType.name,
                    exerciseId = checkpoint.exerciseId,
                    setId = checkpoint.setId,
                    setIndex = checkpoint.setIndex,
                    restOrder = checkpoint.restOrder
                )
            }
        }

        if (recoveryApplied) {
            if (shouldRestartCalibration) {
                resetCurrentCalibrationLoadSelectionState()
                checkpointStore()?.clearRuntimeSnapshot()
            }
            applyTimerRecoveryChoice(recoveryOptions.timerChoice)
            recalculatePlatesForCurrentExerciseAfterRecoveryIfNeeded()
            if (selectedWorkout.value.usePolarDevice) {
                // Leave user on Preparing Polar screen so they can try to connect or skip
                markSessionReady()
                rebuildScreenState()
            } else {
                resumeWorkout()
            }
            skipNextResumeLastState = true
            pendingPostRecoveryTimerReanchor =
                recoveryOptions.timerChoice == TimerRecoveryChoice.CONTINUE
            _showRecoveredWorkoutNotice.value = true
        }

        pendingRecoveryCheckpoint = null
        pendingRecoveryResumeOptions = RecoveryResumeOptions()
        lightScreenUp()
        onEnd()
    }

    private fun doesCurrentStateMatchCheckpointType(checkpoint: WorkoutRecoveryCheckpoint): Boolean {
        val state = workoutState.value
        return when (checkpoint.stateType) {
            RecoveryStateType.SET -> state is WorkoutState.Set
            RecoveryStateType.REST -> state is WorkoutState.Rest
            RecoveryStateType.CALIBRATION_LOAD -> state is WorkoutState.CalibrationLoadSelection
            RecoveryStateType.CALIBRATION_RIR -> state is WorkoutState.CalibrationRIRSelection
            RecoveryStateType.AUTO_REGULATION_RIR -> state is WorkoutState.AutoRegulationRIRSelection
            RecoveryStateType.UNKNOWN -> false
        }
    }

    private fun applyTimerRecoveryChoice(choice: TimerRecoveryChoice) {
        when (val state = workoutState.value) {
            is WorkoutState.Set -> {
                when (val setData = state.currentSetData) {
                    is TimedDurationSetData -> {
                        val normalizedSetData = normalizeTimedDurationTimerBounds(setData)
                        if (normalizedSetData != setData) {
                            state.currentSetData = normalizedSetData
                        }
                        if (choice == TimerRecoveryChoice.RESTART) {
                            state.currentSetData = normalizedSetData.copy(endTimer = normalizedSetData.startTimer)
                            state.startTime = null
                            workoutTimerService.unregisterTimer(state.set.id)
                        } else {
                            reanchorTimedDurationStartTime(state, normalizedSetData)
                        }
                    }

                    is EnduranceSetData -> {
                        if (choice == TimerRecoveryChoice.RESTART) {
                            state.currentSetData = setData.copy(endTimer = 0)
                            state.startTime = null
                            workoutTimerService.unregisterTimer(state.set.id)
                        } else {
                            reanchorEnduranceStartTime(state, setData)
                        }
                    }
                    else -> Unit
                }
            }

            is WorkoutState.Rest -> {
                val setData = normalizeRestTimerBounds(state.currentSetData as? RestSetData ?: return)
                if (setData != state.currentSetData) {
                    state.currentSetData = setData
                }
                if (choice == TimerRecoveryChoice.RESTART) {
                    state.currentSetData = setData.copy(endTimer = setData.startTimer)
                    state.startTime = null
                    workoutTimerService.unregisterTimer(state.set.id)
                } else {
                    reanchorRestStartTime(state, setData)
                }
            }

            else -> Unit
        }

    }

    fun applyPostRecoveryTimerReanchorIfNeeded() {
        if (!pendingPostRecoveryTimerReanchor) return
        pendingPostRecoveryTimerReanchor = false

        when (val state = workoutState.value) {
            is WorkoutState.Set -> when (val setData = state.currentSetData) {
                is TimedDurationSetData -> reanchorTimedDurationStartTime(
                    state,
                    normalizeTimedDurationTimerBounds(setData)
                )
                is EnduranceSetData -> reanchorEnduranceStartTime(state, setData)
                else -> Unit
            }
            is WorkoutState.Rest -> {
                val setData = normalizeRestTimerBounds(state.currentSetData as? RestSetData ?: return)
                reanchorRestStartTime(state, setData)
            }
            else -> Unit
        }
    }

    private fun reanchorTimedDurationStartTime(state: WorkoutState.Set, setData: TimedDurationSetData) {
        val normalizedSetData = normalizeTimedDurationTimerBounds(setData)
        val elapsedMillis = (normalizedSetData.startTimer - normalizedSetData.endTimer).coerceAtLeast(0)
        state.startTime = LocalDateTime.now()
            .minusNanos(elapsedMillis.toLong() * 1_000_000L)
    }

    private fun reanchorEnduranceStartTime(state: WorkoutState.Set, setData: EnduranceSetData) {
        val elapsedMillis = setData.endTimer.coerceAtLeast(0)
        state.startTime = LocalDateTime.now()
            .minusNanos(elapsedMillis.toLong() * 1_000_000L)
    }

    private fun reanchorRestStartTime(state: WorkoutState.Rest, setData: RestSetData) {
        val normalizedSetData = normalizeRestTimerBounds(setData)
        val elapsedSeconds = (normalizedSetData.startTimer - normalizedSetData.endTimer).coerceAtLeast(0)
        state.startTime = LocalDateTime.now().minusSeconds(elapsedSeconds.toLong())
    }

    private fun normalizeRestTimerBounds(data: RestSetData): RestSetData {
        val normalizedStart = data.startTimer.coerceAtLeast(0)
        val normalizedEnd = data.endTimer.coerceIn(0, normalizedStart)
        return if (normalizedStart == data.startTimer && normalizedEnd == data.endTimer) {
            data
        } else {
            data.copy(startTimer = normalizedStart, endTimer = normalizedEnd)
        }
    }

    private fun normalizeTimedDurationTimerBounds(data: TimedDurationSetData): TimedDurationSetData {
        val normalizedStart = data.startTimer.coerceAtLeast(0)
        val normalizedEnd = data.endTimer.coerceIn(0, normalizedStart)
        return if (normalizedStart == data.startTimer && normalizedEnd == data.endTimer) {
            data
        } else {
            data.copy(startTimer = normalizedStart, endTimer = normalizedEnd)
        }
    }

    private fun resetCurrentCalibrationLoadSelectionState() {
        val state = workoutState.value as? WorkoutState.CalibrationLoadSelection ?: return
        state.currentSetData = initializeSetData(state.calibrationSet)
    }

    private fun toEpochMillis(dateTime: LocalDateTime): Long {
        return dateTime.atZone(java.time.ZoneId.systemDefault()).toInstant().toEpochMilli()
    }

    override fun pushAndStoreWorkoutData(
        isDone: Boolean,
        context: Context?,
        forceNotSend: Boolean,
        onEnd: suspend () -> Unit
    ) {
        Log.d(WORKOUT_SYNC_LOG_TAG, "pushAndStoreWorkoutData called: isDone=$isDone, forceNotSend=$forceNotSend")
        super.pushAndStoreWorkoutData(isDone, context, forceNotSend) {
            val currentState = workoutState.value
            if (isDone) {
                val syncContext = resolveSyncContext(context)
                val completedHistoryId = currentWorkoutHistory?.takeIf { it.isDone }?.id
                if (syncContext != null && completedHistoryId != null) {
                    enqueuePendingWorkoutHistoryId(syncContext, completedHistoryId)
                }
            }
            if (currentState is WorkoutState.Set) {
                upsertWorkoutRecord(currentState.exerciseId, currentState.setIndex)
            }

            if (!forceNotSend) {
                Log.d(
                    WORKOUT_SYNC_LOG_TAG,
                    "SYNC_TRACE event=push_store side=wear isDone=$isDone forceNotSend=$forceNotSend state=$currentState"
                )
                Log.d(WORKOUT_SYNC_LOG_TAG, "pushAndStoreWorkoutData: currentState=$currentState")
                val syncRequestMode = resolveWorkoutHistorySyncRequestMode(
                    currentState = currentState,
                    isDone = isDone
                )

                when (syncRequestMode) {
                    WorkoutHistorySyncRequestMode.Immediate -> {
                        requestImmediateWorkoutHistorySync(context)
                    }
                    WorkoutHistorySyncRequestMode.Debounced -> {
                        requestWorkoutHistorySync(context)
                    }
                    null -> {
                        Log.d(WORKOUT_SYNC_LOG_TAG, "pushAndStoreWorkoutData: no sync requested for state=$currentState")
                    }
                }
            }
            onEnd()
        }
    }

    override suspend fun onWorkoutDefinitionChanged(updatedWorkoutStore: WorkoutStore) {
        withContext(Dispatchers.Main) {
            rebuildScreenState()
        }
        val client = dataClient ?: return
        runCatching {
            syncMutex.withLock {
                sendWorkoutStore(client, updatedWorkoutStore)
            }
        }.onFailure { exception ->
            Log.e(WORKOUT_SYNC_LOG_TAG, "Failed to sync updated workout store after equipment change", exception)
        }
    }

    /**
     * Immediately flushes any pending debounced sync operation.
     * Should be called on navigation or lifecycle events to ensure data is synced.
     * Only flushes if phone is connected to prevent sync attempts when mobile app is uninstalled.
     */
    fun flushWorkoutSync() {
        Log.d(
            WORKOUT_SYNC_LOG_TAG,
            "SYNC_TRACE event=sync_flush side=wear pending=${_hasPendingWorkoutSync.value} phoneConnected=$isPhoneConnectedAndHasApp dataClient=${dataClient != null}"
        )
        launchMain {
            syncDebouncer.flush()
        }
    }

    /**
     * Resets sync status to Idle. Called by UI after auto-dismiss.
     */
    fun resetSyncStatus() {
        _syncStatus.value = SyncStatus.Idle
    }
    
    /**
     * Checks if a workout is currently active.
     * Returns false if workoutState is Completed, true otherwise.
     */
    private fun isWorkoutActive(): Boolean {
        val state = workoutState.value
        return state !is WorkoutState.Completed
    }

    private fun resolveSyncContext(context: Context?): Context? {
        return context?.applicationContext ?: applicationContext
    }

    private fun markScheduledSync(context: Context?) {
        _hasPendingWorkoutSync.value = true
        if (pendingSyncContext == null) {
            pendingSyncContext = resolveSyncContext(context)
        }
    }

    private fun markPendingReconnect(context: Context?) {
        _hasPendingWorkoutSync.value = true
        pendingSyncAfterReconnect = true
        if (pendingSyncContext == null) {
            pendingSyncContext = resolveSyncContext(context)
        }
    }

    private fun clearPendingSync() {
        _hasPendingWorkoutSync.value = false
        pendingSyncAfterReconnect = false
        pendingSyncContext = null
    }

    private fun requestWorkoutHistorySync(context: Context?) {
        Log.d(WORKOUT_SYNC_LOG_TAG, "requestWorkoutHistorySync called")
        markScheduledSync(context)
        _syncStatus.value = SyncStatus.Syncing
        startSyncStatusTimeout()
        Log.d(
            WORKOUT_SYNC_LOG_TAG,
            "SYNC_TRACE event=sync_scheduled side=wear pending=${_hasPendingWorkoutSync.value}"
        )
        val syncContext = resolveSyncContext(context)
        launchMain {
            Log.d(WORKOUT_SYNC_LOG_TAG, "requestWorkoutHistorySync: Scheduling debounced sync")
            syncDebouncer.schedule {
                Log.d(WORKOUT_SYNC_LOG_TAG, "requestWorkoutHistorySync: Debounced direct send")
                triggerImmediateWorkoutHistorySync(syncContext)
            }
        }
    }

    private fun requestImmediateWorkoutHistorySync(context: Context?) {
        Log.d(WORKOUT_SYNC_LOG_TAG, "requestImmediateWorkoutHistorySync called")
        markScheduledSync(context)
        _syncStatus.value = SyncStatus.Syncing
        startSyncStatusTimeout()
        val syncContext = resolveSyncContext(context)
        launchMain {
            syncDebouncer.cancel()
            triggerImmediateWorkoutHistorySync(syncContext)
        }
    }

    private fun triggerImmediateWorkoutHistorySync(syncContext: Context?) {
        if (syncContext == null) {
            markPendingReconnect(null)
            return
        }

        // Direct Data Layer sends are reliable enough for E2E-observable intermediate checkpoints
        // and completion, while WorkManager remains the fallback if the send fails.
        sendWorkoutHistoryToPhone(syncContext) { success ->
            if (!success) {
                WorkoutHistorySyncWorker.enqueue(syncContext)
                showSyncRetryingToastIfInactive(syncContext)
            }
            clearPendingSync()
            _syncStatus.value = SyncStatus.Idle
            cancelSyncTimeouts()
        }
    }
    
    // Workout Plan Helper Methods
    
    fun getWorkoutPlanById(planId: UUID): WorkoutPlan? {
        return workoutStore.workoutPlans.find { it.id == planId }
    }
    
    fun getAllWorkoutPlans(): List<WorkoutPlan> {
        return workoutStore.workoutPlans.sortedWith(
            compareBy<WorkoutPlan>(
                { it.name == UNASSIGNED_PLAN_NAME },
                { it.order }
            )
        )
    }
    
    fun getWorkoutsByPlan(planId: UUID?): List<com.gabstra.myworkoutassistant.shared.Workout> {
        val allWorkouts = workoutStore.workouts.filter { it.enabled && it.isActive }
        return if (planId == null) {
            allWorkouts.filter { it.workoutPlanId == null }
        } else {
            allWorkouts.filter { it.workoutPlanId == planId }
        }
    }

    override fun activeSessionOwnerDevice(): SessionOwnerDevice = SessionOwnerDevice.WEAR
}
