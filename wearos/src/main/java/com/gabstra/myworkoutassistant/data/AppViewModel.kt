package com.gabstra.myworkoutassistant.data

import android.content.Context
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
import com.gabstra.myworkoutassistant.shared.ExerciseInfo
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgression
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryStore
import com.gabstra.myworkoutassistant.shared.WorkoutPlan
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutScreenState
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.Node
import android.util.Log
import kotlinx.coroutines.CoroutineExceptionHandler
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.util.UUID
import com.gabstra.myworkoutassistant.data.checkConnection

open class AppViewModel : WorkoutViewModel() {
    
    private var applicationContext: android.content.Context? = null
    
    fun initApplicationContext(context: android.content.Context) {
        applicationContext = context.applicationContext
    }
    
    private val coroutineExceptionHandler = CoroutineExceptionHandler { _, throwable ->
        Log.e("AppViewModel", "Uncaught exception in coroutine", throwable)
        // Log the exception to file via MyApplication if available
        try {
            (applicationContext as? MyApplication)?.logErrorToFile("AppViewModel Coroutine", throwable)
        } catch (e: Exception) {
            Log.e("AppViewModel", "Failed to log exception to file", e)
        }
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

    fun prepareResumeWorkout(incompleteWorkout: WorkoutViewModel.IncompleteWorkout) {
        setSelectedWorkoutId(incompleteWorkout.workoutId)
        pendingResumeWorkoutHistoryId = incompleteWorkout.workoutHistory.id
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
        isSyncingToPhoneTimeoutJob = viewModelScope.launch {
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
        syncStatusTimeoutJob = viewModelScope.launch {
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
        _screenState.value = WorkoutScreenState(
            workoutState = workoutState.value,
            nextWorkoutState = nextWorkoutState.value,
            selectedWorkout = selectedWorkout.value,
            isPaused = isPaused.value,
            hasWorkoutRecord = hasWorkoutRecord.value,
            isResuming = isResuming.value,
            isRefreshing = isRefreshing.value,
            isCustomDialogOpen = isCustomDialogOpen.value,
            enableWorkoutNotificationFlow = enableWorkoutNotificationFlow.value,
            userAge = userAge.value,
            startWorkoutTime = startWorkoutTime,
            enableDimming = enableDimming.value,
            keepScreenOn = keepScreenOn.value,
            currentScreenDimmingState = currentScreenDimmingState.value,
            headerDisplayMode = headerDisplayMode.value,
            hrDisplayMode = hrDisplayMode.value,
        )
    }

    fun sendAll(context: Context) {
        viewModelScope.launch(coroutineExceptionHandler) {
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
                                exerciseInfoDao.getExerciseInfoById(exercise.id)
                            }

                            val workoutRecord = workoutRecordDao.getWorkoutRecordByWorkoutId(it.id)
                            val exerciseSessionProgressions = exerciseSessionProgressionDao.getByWorkoutHistoryId(workoutHistory.id)

                            val errorLogs = try {
                                (context.applicationContext as? MyApplication)?.getErrorLogs() ?: emptyList()
                            } catch (e: Exception) {
                                Log.e("AppViewModel", "Error getting error logs", e)
                                emptyList()
                            }

                            val result = syncMutex.withLock {
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
                            if (result && errorLogs.isNotEmpty()) {
                                try {
                                    (context.applicationContext as? MyApplication)?.clearErrorLogs()
                                } catch (e: Exception) {
                                    Log.e("AppViewModel", "Error clearing error logs", e)
                                }
                            }
                            
                            statuses.add(result)
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

    fun sendWorkoutHistoryToPhone(context: Context, onEnd: (Boolean) -> Unit = {}) {
        viewModelScope.launch(coroutineExceptionHandler + Dispatchers.IO) {
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
                    return@launch
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
                    return@launch
                }

                val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)
                val workoutRecord = workoutRecordDao.getWorkoutRecordByWorkoutId(selectedWorkout.value.id)

                val exerciseInfos =
                    selectedWorkout.value.workoutComponents.filterIsInstance<Exercise>().mapNotNull {
                        exerciseInfoDao.getExerciseInfoById(it.id)
                    } + selectedWorkout.value.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }.mapNotNull {
                        exerciseInfoDao.getExerciseInfoById(it.id)
                    }

                val exerciseSessionProgressions = exerciseSessionProgressionDao.getByWorkoutHistoryId(workoutHistory.id)

                // Note: Error logs will be included in pushAndStoreWorkoutData instead
                // since we don't have context here
                val result = dataClient?.let {
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
                } ?: false

                withContext(Dispatchers.Main) {
                    _isSyncingToPhone.value = false
                    cancelSyncTimeouts()
                    onEnd(result)
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

        super.resumeWorkoutFromRecord {
            lightScreenUp()
            onEnd()
        }
    }

    override fun pushAndStoreWorkoutData(
        isDone: Boolean,
        context: Context?,
        forceNotSend: Boolean,
        onEnd: suspend () -> Unit
    ) {
        super.pushAndStoreWorkoutData(isDone, context, forceNotSend) {
            if (!forceNotSend) {
                val currentState = workoutState.value
                // We want to send workout history whenever we finish storing a set
                // (including the last set), so that incomplete workouts can be resumed
                // on mobile. The completion screen will call this again with
                // isDone=true but forceNotSend=true so we won't resend.
                // When isDone=true, we must sync the final workout state even if the
                // state has already transitioned to Completed.
                val shouldSendData = currentState is WorkoutState.Set || isDone

                if(currentState is WorkoutState.Set){
                    upsertWorkoutRecord(currentState.exerciseId,currentState.setIndex)
                }

                if (shouldSendData) {
                    requestWorkoutHistorySync(context)
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
        // Only flush if phone is connected - prevents sync attempts when mobile app is uninstalled
        if (!isPhoneConnectedAndHasApp || dataClient == null) {
            Log.d("AppViewModel", "Skipping flushWorkoutSync - phone not connected or dataClient unavailable")
            markPendingReconnect(null)
            return
        }
        viewModelScope.launch(coroutineExceptionHandler) {
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
        markScheduledSync(context)
        val syncContext = resolveSyncContext(context)
        viewModelScope.launch(coroutineExceptionHandler) {
            syncDebouncer.schedule {
                performWorkoutHistorySync(syncContext)
            }
        }
    }

    private suspend fun performWorkoutHistorySync(context: Context?) {
        val syncContext = resolveSyncContext(context)
        val client = dataClient
        if (client == null) {
            markPendingReconnect(syncContext)
            return
        }

        if (syncContext != null) {
            val hasConnection = checkConnection(syncContext)
            if (!hasConnection) {
                markPendingReconnect(syncContext)
                return
            }
        }

        clearPendingSync()
        try {
            _syncStatus.value = SyncStatus.Syncing
            startSyncStatusTimeout()

            // Read current state at execution time (includes all accumulated sets)
            val exerciseInfos = mutableListOf<ExerciseInfo>()
            val exercises = selectedWorkout.value.workoutComponents.filterIsInstance<Exercise>() +
                    selectedWorkout.value.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }

            exercises.forEach { exercise ->
                exerciseInfoDao.getExerciseInfoById(exercise.id)?.let {
                    exerciseInfos.add(it)
                }
            }

            val exerciseSessionProgressions = exerciseSessionProgressionDao.getByWorkoutHistoryId(currentWorkoutHistory!!.id)

            val errorLogs = try {
                (syncContext?.applicationContext as? MyApplication)?.getErrorLogs() ?: emptyList()
            } catch (e: Exception) {
                Log.e("AppViewModel", "Error getting error logs", e)
                emptyList()
            }

            val result = syncMutex.withLock {
                sendWorkoutHistoryStore(
                    client,
                    WorkoutHistoryStore(
                        WorkoutHistory = currentWorkoutHistory!!,
                        SetHistories = executedSetsHistory,
                        ExerciseInfos = exerciseInfos,
                        WorkoutRecord = _workoutRecord,
                        ExerciseSessionProgressions = exerciseSessionProgressions,
                        ErrorLogs = errorLogs
                    ),
                    syncContext
                )
            }

            // Clear error logs after successful send
            if (result && errorLogs.isNotEmpty() && syncContext != null) {
                try {
                    (syncContext.applicationContext as? MyApplication)?.clearErrorLogs()
                } catch (e: Exception) {
                    Log.e("AppViewModel", "Error clearing error logs", e)
                }
            }

            // Set status based on result
            _syncStatus.value = if (result) SyncStatus.Success else SyncStatus.Failure
            cancelSyncTimeouts()

            // Don't show immediate success toast - wait for completion message
            // Success toast will be shown when SYNC_COMPLETE is received
            if (syncContext != null && !result) {
                withContext(Dispatchers.Main) {
                    if (!isWorkoutActive()) {
                        Toast.makeText(syncContext, "Failed to send data to phone", Toast.LENGTH_SHORT).show()
                    }
                }
            }
        } catch (e: Exception) {
            Log.e("AppViewModel", "Error in debounced sync", e)
            // Log detailed error for debugging but show generic message to user
            Log.d("AppViewModel", "Detailed sync error: ${e.message}")
            _syncStatus.value = SyncStatus.Failure
            cancelSyncTimeouts()
            if (syncContext != null) {
                withContext(Dispatchers.Main) {
                    if (!isWorkoutActive()) {
                        Toast.makeText(syncContext, "Sync failed", Toast.LENGTH_LONG).show()
                    }
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
