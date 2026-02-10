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
import com.gabstra.myworkoutassistant.shared.ExerciseInfo
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgression
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryStore
import com.gabstra.myworkoutassistant.shared.WorkoutPlan
import com.gabstra.myworkoutassistant.shared.workout.ui.WorkoutScreenState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.Node
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.time.LocalDateTime
import java.time.ZoneId
import java.util.UUID
import com.gabstra.myworkoutassistant.data.checkConnection
import com.gabstra.myworkoutassistant.sync.WorkoutHistorySyncWorker

open class AppViewModel : WorkoutViewModel() {

    companion object {
        private const val SYNCED_WORKOUT_HISTORY_IDS_PREFS = "synced_workout_history_ids"
        private const val SYNCED_IDS_KEY = "ids"
    }

    private var applicationContext: android.content.Context? = null
    private var lastCheckpointFingerprint: String? = null
    private var pendingRecoveryCheckpoint: WorkoutRecoveryCheckpoint? = null

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

    private fun getSyncedWorkoutHistoryIds(context: Context): Set<UUID> {
        val prefs = context.getSharedPreferences(SYNCED_WORKOUT_HISTORY_IDS_PREFS, Context.MODE_PRIVATE)
        val ids = prefs.getStringSet(SYNCED_IDS_KEY, null) ?: emptySet()
        return ids.mapNotNull { runCatching { UUID.fromString(it) }.getOrNull() }.toSet()
    }

    private fun addSyncedWorkoutHistoryId(context: Context, id: UUID) {
        val prefs = context.getSharedPreferences(SYNCED_WORKOUT_HISTORY_IDS_PREFS, Context.MODE_PRIVATE)
        val current = prefs.getStringSet(SYNCED_IDS_KEY, null)?.toMutableSet() ?: mutableSetOf()
        current.add(id.toString())
        prefs.edit().putStringSet(SYNCED_IDS_KEY, current).apply()
    }

    /** Call before sending a store so SYNC_COMPLETE can mark that history as synced. */
    private fun registerPendingSyncTransaction(transactionId: String, workoutHistoryId: UUID) {
        pendingSyncTransactions[transactionId] = workoutHistoryId
    }

    /** Called when SYNC_COMPLETE broadcast is received; marks the corresponding history as synced. */
    fun markHistorySyncedForTransaction(transactionId: String?) {
        if (transactionId == null) return
        val historyId = pendingSyncTransactions.remove(transactionId) ?: return
        val ctx = applicationContext ?: return
        addSyncedWorkoutHistoryId(ctx, historyId)
        Log.d("AppViewModel", "Marked workout history $historyId as synced for transaction $transactionId")
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

    private val _showResumeWorkoutDialog = mutableStateOf(false)
    val showResumeWorkoutDialog: State<Boolean> = _showResumeWorkoutDialog

    private val _incompleteWorkouts = mutableStateOf<List<com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel.IncompleteWorkout>>(emptyList())
    val incompleteWorkouts: State<List<com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel.IncompleteWorkout>> = _incompleteWorkouts

    fun showResumeWorkoutDialog(incompleteWorkouts: List<com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel.IncompleteWorkout>) {
        if (incompleteWorkouts.isEmpty()) {
            hideResumeWorkoutDialog()
            return
        }
        _incompleteWorkouts.value = incompleteWorkouts
        _showResumeWorkoutDialog.value = true
    }

    fun hideResumeWorkoutDialog() {
        _showResumeWorkoutDialog.value = false
        _incompleteWorkouts.value = emptyList()
    }

    private val _showRecoveryPrompt = mutableStateOf(false)
    val showRecoveryPrompt: State<Boolean> = _showRecoveryPrompt

    private val _recoveryWorkout = mutableStateOf<com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel.IncompleteWorkout?>(null)
    val recoveryWorkout: State<com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel.IncompleteWorkout?> = _recoveryWorkout

    private val _showRecoveredWorkoutNotice = mutableStateOf(false)
    val showRecoveredWorkoutNotice: State<Boolean> = _showRecoveredWorkoutNotice

    fun consumeRecoveredWorkoutNotice() {
        _showRecoveredWorkoutNotice.value = false
    }

    internal fun showRecoveryPrompt(
        incompleteWorkout: com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel.IncompleteWorkout,
        checkpoint: WorkoutRecoveryCheckpoint?
    ) {
        _recoveryWorkout.value = incompleteWorkout
        _showRecoveryPrompt.value = true
        pendingRecoveryCheckpoint = checkpoint
    }

    fun hideRecoveryPrompt() {
        _showRecoveryPrompt.value = false
        _recoveryWorkout.value = null
    }

    fun prepareResumeWorkout(incompleteWorkout: WorkoutViewModel.IncompleteWorkout) {
        setSelectedWorkoutId(incompleteWorkout.workoutId)
        pendingResumeWorkoutHistoryId = incompleteWorkout.workoutHistory.id
    }

    internal fun getSavedRecoveryCheckpoint(): WorkoutRecoveryCheckpoint? {
        return checkpointStore()?.load()
    }

    fun clearRecoveryCheckpoint() {
        checkpointStore()?.clear()
        lastCheckpointFingerprint = null
        pendingRecoveryCheckpoint = null
    }

    fun clearWorkoutInProgressFlag() {
        val context = applicationContext ?: return
        val prefs = context.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
        prefs.edit { putBoolean("isWorkoutInProgress", false) }
    }

    fun discardIncompleteWorkout(incompleteWorkout: WorkoutViewModel.IncompleteWorkout) {
        launchIO {
            workoutRecordDao.deleteByWorkoutId(incompleteWorkout.workoutId)
        }
    }

    private val _hrDisplayMode = mutableStateOf(0)
    val hrDisplayMode: State<Int> = _hrDisplayMode.asIntState()
    private val _headerDisplayMode = mutableStateOf(0)
    val headerDisplayMode: State<Int> = _headerDisplayMode.asIntState()

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
            delay(10000L) // 10 seconds timeout
            if (_isSyncingToPhone.value) {
                // Only reset if still syncing (sync didn't complete)
                _isSyncingToPhone.value = false
                Log.w("AppViewModel", "Sync timeout: resetting _isSyncingToPhone after 10 seconds")
            }
        }
    }
    
    /**
     * Starts a timeout coroutine that resets _syncStatus after 10 seconds if still syncing.
     */
    private fun startSyncStatusTimeout() {
        syncStatusTimeoutJob?.cancel()
        syncStatusTimeoutJob = launchDefault {
            delay(10000L) // 10 seconds timeout
            if (_syncStatus.value == SyncStatus.Syncing) {
                // Only reset if still syncing (sync didn't complete)
                _syncStatus.value = SyncStatus.Idle
                Log.w("AppViewModel", "Sync timeout: resetting _syncStatus after 10 seconds")
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

        // Clear checkpoint only when workout is completed.
        if (screenState.workoutState is WorkoutState.Completed) {
            checkpointStore()?.clear()
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
            else -> null
        }

        val setId = when (currentState) {
            is WorkoutState.Set -> currentState.set.id
            is WorkoutState.Rest -> currentState.set.id
            is WorkoutState.CalibrationLoadSelection -> currentState.calibrationSet.id
            is WorkoutState.CalibrationRIRSelection -> currentState.calibrationSet.id
            else -> null
        }

        val setIndex = when (currentState) {
            is WorkoutState.Set -> currentState.setIndex
            is WorkoutState.CalibrationLoadSelection -> currentState.setIndex
            is WorkoutState.CalibrationRIRSelection -> currentState.setIndex
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
            exerciseId = exerciseId,
            setId = setId,
            setIndex = setIndex,
            restOrder = restOrder,
            setStartEpochMs = setStartEpochMs,
            updatedAtEpochMs = System.currentTimeMillis()
        )

        val fingerprint = "${checkpoint.workoutId}:${checkpoint.stateType}:${checkpoint.exerciseId}:${checkpoint.setId}:${checkpoint.setIndex}:${checkpoint.restOrder}:${checkpoint.setStartEpochMs}"
        if (fingerprint == lastCheckpointFingerprint) return

        WorkoutRecoveryCheckpointStore(context).save(checkpoint)
        lastCheckpointFingerprint = fingerprint
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
                                Log.e("AppViewModel", "Error getting error logs", e)
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
                                        ErrorLogs = errorLogs
                                    ),
                                    context
                                )
                            }
                            
                            // Clear error logs after successful send
                            if (success && errorLogs.isNotEmpty()) {
                                try {
                                    (context.applicationContext as? MyApplication)?.clearErrorLogs()
                                } catch (e: Exception) {
                                    Log.e("AppViewModel", "Error clearing error logs", e)
                                }
                            }
                            
                            statuses.add(success)
                        } catch (e: Exception) {
                            Log.e("AppViewModel", "Error sending workout data for ${it.id}", e)
                            statuses.add(false)
                            // Log detailed error for debugging but show generic message to user
                            Log.d("AppViewModel", "Detailed sync error: ${e.message}")
                            withContext(Dispatchers.Main) {
                                if (!isWorkoutActive()) {
                                    Toast.makeText(context, "Sync failed", Toast.LENGTH_LONG).show()
                                }
                            }
                        }
                    }

                    // Don't show immediate success toast - wait for completion message
                    // Success toast will be shown when SYNC_COMPLETE is received
                }
            } catch (e: Exception) {
                Log.e("AppViewModel", "Error in sendAll", e)
                // Log detailed error for debugging but show generic message to user
                Log.d("AppViewModel", "Detailed sync error: ${e.message}")
                withContext(Dispatchers.Main) {
                    if (!isWorkoutActive()) {
                        Toast.makeText(context, "Sync failed", Toast.LENGTH_LONG).show()
                    }
                }
            }
        }
    }

    /**
     * Sends only workout histories that have not yet been confirmed synced (additive catch-up at start).
     * Call when app is initialized and phone is connected.
     */
    fun sendUnsyncedHistories(context: Context) {
        launchMain {
            try {
                withContext(Dispatchers.IO) {
                    val client = dataClient ?: return@withContext
                    val syncedIds = getSyncedWorkoutHistoryIds(context)
                    val allCompleted = workoutHistoryDao.getAllWorkoutHistoriesByIsDone(true)
                    val unsynced = allCompleted.filter { it.id !in syncedIds }
                    if (unsynced.isEmpty()) return@withContext

                    Log.d("DataLayerSync", "sendUnsyncedHistories: sending ${unsynced.size} unsynced histories")
                    unsynced.forEachIndexed { index, workoutHistory ->
                        try {
                            Log.d("DataLayerSync", "Sending unsynced history id=${workoutHistory.id} (${index + 1} of ${unsynced.size})")
                            val workout = workoutStore.workouts.find { it.id == workoutHistory.workoutId }
                                ?: return@forEachIndexed
                            val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)
                            val exercises = workout.workoutComponents.filterIsInstance<Exercise>() +
                                workout.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }
                            val exerciseInfos = exercises.mapNotNull { getExerciseInfoDao().getExerciseInfoById(it.id) }
                            val workoutRecord = workoutRecordDao.getWorkoutRecordByWorkoutId(workout.id)
                            val exerciseSessionProgressions = exerciseSessionProgressionDao.getByWorkoutHistoryId(workoutHistory.id)
                            val errorLogs = try {
                                (context.applicationContext as? MyApplication)?.getErrorLogs() ?: emptyList()
                            } catch (e: Exception) {
                                Log.e("AppViewModel", "Error getting error logs", e)
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
                                        ErrorLogs = errorLogs
                                    ),
                                    context,
                                    transactionId
                                )
                            }
                            if (success && errorLogs.isNotEmpty()) {
                                try {
                                    (context.applicationContext as? MyApplication)?.clearErrorLogs()
                                } catch (e: Exception) {
                                    Log.e("AppViewModel", "Error clearing error logs", e)
                                }
                            }
                        } catch (e: Exception) {
                            Log.e("AppViewModel", "Error sending unsynced history ${workoutHistory.id}", e)
                        }
                    }
                }
            } catch (e: Exception) {
                Log.e("AppViewModel", "Error in sendUnsyncedHistories", e)
            }
        }
    }

    fun sendWorkoutHistoryToPhone(context: Context, onEnd: (Boolean) -> Unit = {}) {
        launchIO {
            try {
                // Check connection before setting syncing state
                val hasConnection = checkConnection(context)
                if (!hasConnection) {
                    withContext(Dispatchers.Main) {
                        if (!isWorkoutActive()) {
                            Toast.makeText(context, "Phone not connected", Toast.LENGTH_SHORT).show()
                        }
                        onEnd(false)
                    }
                    return@launchIO
                }
                
                // Only set syncing state after connection check succeeds
                withContext(Dispatchers.Main) {
                    _isSyncingToPhone.value = true
                    startIsSyncingToPhoneTimeout()
                }
                
                val workoutHistory =
                    workoutHistoryDao.getLatestWorkoutHistoryByWorkoutId(selectedWorkout.value.id)

                if (workoutHistory == null) {
                    withContext(Dispatchers.Main) {
                        _isSyncingToPhone.value = false
                        cancelSyncTimeouts()
                        onEnd(false)
                    }
                    return@launchIO
                }

                val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)
                val workoutRecord = workoutRecordDao.getWorkoutRecordByWorkoutId(selectedWorkout.value.id)

                val exerciseInfos =
                    selectedWorkout.value.workoutComponents.filterIsInstance<Exercise>().mapNotNull {
                        getExerciseInfoDao().getExerciseInfoById(it.id)
                    } + selectedWorkout.value.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }.mapNotNull {
                        getExerciseInfoDao().getExerciseInfoById(it.id)
                    }

                val exerciseSessionProgressions = exerciseSessionProgressionDao.getByWorkoutHistoryId(workoutHistory.id)

                // Note: Error logs will be included in pushAndStoreWorkoutData instead
                // since we don't have context here
                val (success, _) = dataClient?.let {
                    syncMutex.withLock {
                        sendWorkoutHistoryStore(
                            it, WorkoutHistoryStore(
                                WorkoutHistory = workoutHistory,
                                SetHistories = setHistories,
                                ExerciseInfos = exerciseInfos,
                                WorkoutRecord = workoutRecord,
                                ExerciseSessionProgressions = exerciseSessionProgressions
                            ),
                            context
                        )
                    }
                } ?: Pair(false, "")

                withContext(Dispatchers.Main) {
                    _isSyncingToPhone.value = false
                    cancelSyncTimeouts()
                    onEnd(success)
                }
            } catch (e: Exception) {
                Log.e("AppViewModel", "Error sending workout history to phone", e)
                withContext(Dispatchers.Main) {
                    _isSyncingToPhone.value = false
                    cancelSyncTimeouts()
                    // Log detailed error for debugging but show generic message to user
                    Log.d("AppViewModel", "Detailed sync error: ${e.message}")
                    if (!isWorkoutActive()) {
                        Toast.makeText(context, "Sync failed", Toast.LENGTH_LONG).show()
                    }
                    onEnd(false)
                }
            }
        }
    }

    override fun startWorkout() {
        _headerDisplayMode.value = 0
        _hrDisplayMode.value = 0
        super.startWorkout()
    }

    override fun goToNextState() {
        super.goToNextState()
        reEvaluateDimmingForCurrentState()
    }

    override fun resumeWorkoutFromRecord(onEnd: suspend () -> Unit) {
        _headerDisplayMode.value = 0
        _hrDisplayMode.value = 0
        val checkpoint = pendingRecoveryCheckpoint ?: getSavedRecoveryCheckpoint()
        super.resumeWorkoutFromRecord {
            val selectedWorkoutId = selectedWorkout.value.id
            val checkpointApplied = if (checkpoint != null && checkpoint.workoutId == selectedWorkoutId) {
                moveToRecoveredState(
                    stateType = checkpoint.stateType.name,
                    exerciseId = checkpoint.exerciseId,
                    setId = checkpoint.setId,
                    setIndex = checkpoint.setIndex,
                    restOrder = checkpoint.restOrder
                )
            } else {
                false
            }

            if (checkpointApplied) {
                checkpoint?.let { applyTimerRecoveryFromCheckpoint(it) }
                _showRecoveredWorkoutNotice.value = true
            }

            pendingRecoveryCheckpoint = null
            lightScreenUp()
            onEnd()
        }
    }

    private fun applyTimerRecoveryFromCheckpoint(checkpoint: WorkoutRecoveryCheckpoint) {
        val setState = workoutState.value as? WorkoutState.Set ?: return
        val setStartEpochMs = checkpoint.setStartEpochMs ?: return

        val nowEpochMs = System.currentTimeMillis()
        val elapsedMs = (nowEpochMs - setStartEpochMs).coerceAtLeast(0L).toInt()
        val setData = setState.currentSetData

        when (setData) {
            is TimedDurationSetData -> {
                val remainingMs = (setData.startTimer - elapsedMs).coerceAtLeast(0)
                setState.currentSetData = setData.copy(endTimer = remainingMs)
                if (remainingMs > 0) {
                    setState.startTime = fromEpochMillis(setStartEpochMs)
                }
            }

            is EnduranceSetData -> {
                val elapsedClamped = elapsedMs.coerceAtMost(setData.startTimer)
                setState.currentSetData = setData.copy(endTimer = elapsedClamped)
                if (elapsedClamped < setData.startTimer) {
                    setState.startTime = fromEpochMillis(setStartEpochMs)
                }
            }
            else -> Unit
        }
    }

    private fun toEpochMillis(dateTime: LocalDateTime): Long {
        return dateTime.atZone(ZoneId.systemDefault()).toInstant().toEpochMilli()
    }

    private fun fromEpochMillis(epochMs: Long): LocalDateTime {
        return LocalDateTime.ofInstant(
            java.time.Instant.ofEpochMilli(epochMs),
            ZoneId.systemDefault()
        )
    }

    override fun pushAndStoreWorkoutData(
        isDone: Boolean,
        context: Context?,
        forceNotSend: Boolean,
        onEnd: suspend () -> Unit
    ) {
        Log.d("WorkoutSync", "pushAndStoreWorkoutData called: isDone=$isDone, forceNotSend=$forceNotSend")
        super.pushAndStoreWorkoutData(isDone, context, forceNotSend) {
            val currentState = workoutState.value
            if (currentState is WorkoutState.Set) {
                upsertWorkoutRecord(currentState.exerciseId, currentState.setIndex)
            }

            if (!forceNotSend) {
                Log.d(
                    "WorkoutSync",
                    "SYNC_TRACE event=push_store side=wear isDone=$isDone forceNotSend=$forceNotSend state=$currentState"
                )
                Log.d("WorkoutSync", "pushAndStoreWorkoutData: currentState=$currentState")
                // We want to send workout history whenever we finish storing a set
                // (including the last set), so that incomplete workouts can be resumed
                // on mobile. The completion screen will call this again with
                // isDone=true but forceNotSend=true so we won't resend.
                // When isDone=true, we must sync the final workout state even if the
                // state has already transitioned to Completed.
                val shouldSendData = currentState is WorkoutState.Set || isDone

                if (shouldSendData) {
                    Log.d("WorkoutSync", "pushAndStoreWorkoutData: shouldSendData=true, calling requestWorkoutHistorySync")
                    requestWorkoutHistorySync(context)
                } else {
                    Log.d("WorkoutSync", "pushAndStoreWorkoutData: shouldSendData=false, skipping sync")
                }
            }
            onEnd()
        }
    }

    /**
     * Immediately flushes any pending debounced sync operation.
     * Should be called on navigation or lifecycle events to ensure data is synced.
     * Only flushes if phone is connected to prevent sync attempts when mobile app is uninstalled.
     */
    fun flushWorkoutSync() {
        Log.d(
            "WorkoutSync",
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
        Log.d("WorkoutSync", "requestWorkoutHistorySync called")
        markScheduledSync(context)
        _syncStatus.value = SyncStatus.Syncing
        startSyncStatusTimeout()
        Log.d(
            "WorkoutSync",
            "SYNC_TRACE event=sync_scheduled side=wear pending=${_hasPendingWorkoutSync.value}"
        )
        val syncContext = resolveSyncContext(context)
        launchMain {
            Log.d("WorkoutSync", "requestWorkoutHistorySync: Scheduling debounced sync")
            syncDebouncer.schedule {
                Log.d("WorkoutSync", "requestWorkoutHistorySync: Debounced enqueue to worker")
                if (syncContext != null) {
                    WorkoutHistorySyncWorker.enqueue(syncContext)
                    clearPendingSync()
                    _syncStatus.value = SyncStatus.Idle
                    cancelSyncTimeouts()
                } else {
                    markPendingReconnect(null)
                }
            }
        }
    }
    
    // Workout Plan Helper Methods
    
    fun getWorkoutPlanById(planId: UUID): WorkoutPlan? {
        return workoutStore.workoutPlans.find { it.id == planId }
    }
    
    fun getAllWorkoutPlans(): List<WorkoutPlan> {
        return workoutStore.workoutPlans.sortedBy { it.order }
    }
    
    fun getWorkoutsByPlan(planId: UUID?): List<com.gabstra.myworkoutassistant.shared.Workout> {
        val allWorkouts = workoutStore.workouts.filter { it.enabled && it.isActive }
        return if (planId == null) {
            allWorkouts.filter { it.workoutPlanId == null }
        } else {
            allWorkouts.filter { it.workoutPlanId == planId }
        }
    }
}

