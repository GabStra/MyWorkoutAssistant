package com.gabstra.myworkoutassistant.sync

import android.content.Context
import android.util.Log
import androidx.core.content.edit
import androidx.work.WorkInfo
import androidx.work.WorkManager
import com.gabstra.myworkoutassistant.checkWearSyncEndpoint
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.calculateWorkoutStoreHash
import com.gabstra.myworkoutassistant.shared.datalayer.SyncPhase
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Coordinates automatic phone→Wear sync after phone-originated persistence:
 * debounced enqueue when idle, a single replaceable pending follow-up while sync is running,
 * and one follow-up enqueue after a successful sync when pending was set.
 */
object PhoneToWatchSyncCoordinator {
    data class ManualSyncUiState(
        val phase: SyncPhase,
        val progress: Float
    )

    private const val TAG = "PhoneToWatchSyncCoordinator"
    private const val DEBOUNCE_MS = 30_000L
    /** Defer follow-up enqueue until [MobileSyncToWatchWorker.doWork] has returned so WorkManager is not still RUNNING. */
    private const val FOLLOW_UP_ENQUEUE_DELAY_MS = 100L
    private const val PREFS_NAME = "phone_to_watch_sync_coordinator"
    private const val KEY_PENDING_FOLLOW_UP = "pending_follow_up_sync"
    private const val KEY_PENDING_MANUAL_OVERRIDE = "pending_manual_override_sync"
    private const val KEY_LAST_REQUESTED_AUTO_FINGERPRINT = "last_requested_auto_fingerprint"
    private const val KEY_LAST_COMPLETED_AUTO_FINGERPRINT = "last_completed_auto_fingerprint"

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val mutex = Mutex()
    private var debounceJob: Job? = null
    private val pendingFollowUp = AtomicBoolean(false)
    private val pendingManualOverride = AtomicBoolean(false)
    private val isWorkerRunning = AtomicBoolean(false)
    private val automaticSyncState = AutomaticSyncFingerprintState()
    private val _manualSyncProgress = MutableStateFlow<Float?>(null)
    val manualSyncProgress = _manualSyncProgress.asStateFlow()
    private val _manualSyncUiState = MutableStateFlow<ManualSyncUiState?>(null)
    val manualSyncUiState = _manualSyncUiState.asStateFlow()

    private var installed = false

    private fun setPendingFollowUp(context: Context, pending: Boolean) {
        pendingFollowUp.set(pending)
        context.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit {
            putBoolean(KEY_PENDING_FOLLOW_UP, pending)
        }
    }

    private fun setPendingManualOverride(context: Context, pending: Boolean) {
        pendingManualOverride.set(pending)
        context.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit {
            putBoolean(KEY_PENDING_MANUAL_OVERRIDE, pending)
        }
    }

    private fun clearPendingSyncFlags(context: Context) {
        pendingFollowUp.set(false)
        pendingManualOverride.set(false)
        context.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit {
            putBoolean(KEY_PENDING_FOLLOW_UP, false)
            putBoolean(KEY_PENDING_MANUAL_OVERRIDE, false)
        }
    }

    private fun setLastRequestedAutomaticFingerprint(context: Context, fingerprint: String?) {
        automaticSyncState.lastRequestedFingerprint = fingerprint
        context.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit {
            putString(KEY_LAST_REQUESTED_AUTO_FINGERPRINT, fingerprint)
        }
    }

    private fun setLastCompletedAutomaticFingerprint(context: Context, fingerprint: String?) {
        automaticSyncState.lastCompletedFingerprint = fingerprint
        context.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit {
            putString(KEY_LAST_COMPLETED_AUTO_FINGERPRINT, fingerprint)
        }
    }

    private fun restoreAutomaticFingerprintState(context: Context) {
        val prefs = context.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        automaticSyncState.lastRequestedFingerprint = prefs.getString(KEY_LAST_REQUESTED_AUTO_FINGERPRINT, null)
        automaticSyncState.lastCompletedFingerprint = prefs.getString(KEY_LAST_COMPLETED_AUTO_FINGERPRINT, null)
    }

    private suspend fun calculatePersistedWorkoutStoreFingerprint(context: Context): String {
        return withContext(Dispatchers.IO) {
            val workoutStore = WorkoutStoreRepository(context.applicationContext.filesDir).getWorkoutStore()
            calculateWorkoutStoreHash(workoutStore)
        }
    }

    private suspend fun hasRunningSyncWork(context: Context): Boolean =
        WorkManager.getInstance(context.applicationContext)
            .getWorkInfosForUniqueWorkFlow(MobileSyncToWatchWorker.UNIQUE_WORK_NAME)
            .first()
            .any { workInfo -> workInfo.state == WorkInfo.State.RUNNING }

    /**
     * Subscribes to WorkManager state for the mobile sync worker. Call once from [android.app.Activity.onCreate] or equivalent.
     */
    fun install(context: Context) {
        if (installed) return
        installed = true
        val appContext = context.applicationContext
        restoreAutomaticFingerprintState(appContext)
        scope.launch {
            WorkManager.getInstance(appContext)
                .getWorkInfosForUniqueWorkFlow(MobileSyncToWatchWorker.UNIQUE_WORK_NAME)
                .collect { infos ->
                    val running = infos.any { it.state == WorkInfo.State.RUNNING }
                    isWorkerRunning.set(running)
                }
        }
        scope.launch {
            delay(400)
            val prefs = appContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val hadPendingManualOverride = prefs.getBoolean(KEY_PENDING_MANUAL_OVERRIDE, false)
            val hadPendingFollowUp = prefs.getBoolean(KEY_PENDING_FOLLOW_UP, false)
            if (hadPendingManualOverride || hadPendingFollowUp) {
                mutex.withLock {
                    clearPendingSyncFlags(appContext)
                }
                if (hadPendingManualOverride) {
                    MobileSyncToWatchWorker.enqueueManual(appContext)
                    Log.d(TAG, "install: had persisted manual override, enqueued immediate mobile sync to watch")
                } else if (automaticSyncState.hasUnsentAutomaticState()) {
                    MobileSyncToWatchWorker.enqueue(appContext)
                    Log.d(TAG, "install: had persisted pending follow-up, enqueued mobile sync to watch")
                } else {
                    Log.d(TAG, "install: dropped stale pending follow-up because latest automatic state was already sent")
                }
            }
        }
    }

    /**
     * Called after phone-originated data has been persisted. Debounces and enqueues [MobileSyncToWatchWorker], or sets a
     * single replaceable pending follow-up if a sync is already running.
     */
    suspend fun onPhoneDataPersisted(context: Context) {
        if (PhoneSyncToWatchSuppressor.shouldSuppressPhoneToWatchSync()) {
            Log.d(TAG, "onPhoneDataPersisted: skipped (Wear-inbound apply)")
            return
        }
        val appContext = context.applicationContext
        val latestFingerprint = calculatePersistedWorkoutStoreFingerprint(appContext)
        mutex.withLock {
            if (automaticSyncState.shouldSkipNewAutomaticRequest(latestFingerprint)) {
                Log.d(TAG, "onPhoneDataPersisted: skipped duplicate automatic state fingerprint=$latestFingerprint")
                return
            }
            setLastRequestedAutomaticFingerprint(appContext, latestFingerprint)
            if (isWorkerRunning.get()) {
                setPendingFollowUp(appContext, true)
                Log.d(TAG, "onPhoneDataPersisted: sync running, pending follow-up set for fingerprint=$latestFingerprint")
                return
            }
            debounceJob?.cancel()
            val requestedFingerprint = latestFingerprint
            val scheduledJob = scope.launch {
                delay(DEBOUNCE_MS)
                val currentJob = currentCoroutineContext()[Job]
                mutex.withLock {
                    try {
                        if (PhoneSyncToWatchSuppressor.shouldSuppressPhoneToWatchSync()) {
                            return@withLock
                        }
                        if (automaticSyncState.lastRequestedFingerprint != requestedFingerprint) {
                            Log.d(TAG, "debounce completed after newer automatic state replaced fingerprint=$requestedFingerprint")
                            return@withLock
                        }
                        if (!automaticSyncState.hasUnsentAutomaticState()) {
                            Log.d(TAG, "debounce completed but automatic state was already covered fingerprint=$requestedFingerprint")
                            return@withLock
                        }
                        if (isWorkerRunning.get()) {
                            setPendingFollowUp(appContext, true)
                            Log.d(TAG, "debounce completed while sync running, pending follow-up set for fingerprint=$requestedFingerprint")
                        } else {
                            MobileSyncToWatchWorker.enqueue(appContext)
                            Log.d(TAG, "debounce completed, enqueued mobile sync to watch for fingerprint=$requestedFingerprint")
                        }
                    } finally {
                        if (debounceJob === currentJob) {
                            debounceJob = null
                        }
                    }
                }
            }
            debounceJob = scheduledJob
        }
    }

    /**
     * Cancels an in-flight debounced sync timer and runs that sync immediately (or sets a pending
     * follow-up if a sync is already running). If there is no debounced sync pending, does nothing —
     * otherwise every lifecycle pause would enqueue a redundant full sync.
     */
    suspend fun flushDebouncedSyncToWatch(context: Context) {
        if (PhoneSyncToWatchSuppressor.shouldSuppressPhoneToWatchSync()) {
            return
        }
        val appContext = context.applicationContext
        mutex.withLock {
            val hadPendingDebounce = debounceJob != null
            debounceJob?.cancel()
            debounceJob = null
            if (!hadPendingDebounce) {
                return@withLock
            }
            if (!automaticSyncState.hasUnsentAutomaticState()) {
                Log.d(TAG, "flush: skipped because pending debounce was already covered by a successful sync")
                return@withLock
            }
            if (isWorkerRunning.get()) {
                setPendingFollowUp(appContext, true)
                Log.d(TAG, "flush: sync running, pending follow-up set")
            } else {
                MobileSyncToWatchWorker.enqueue(appContext)
                Log.d(TAG, "flush: enqueued mobile sync to watch")
            }
        }
    }

    /**
     * User chose "Sync with Watch" from the menu: cancel debounce and ensure a sync runs (or pending tail if busy).
     */
    suspend fun requestManualSyncToWatch(context: Context): Boolean {
        val appContext = context.applicationContext
        val hasRunningWork = hasRunningSyncWork(appContext)
        mutex.withLock {
            debounceJob?.cancel()
            debounceJob = null
            if (hasRunningWork || isWorkerRunning.get()) {
                setManualSyncState(SyncPhase.CONNECTING, 0f)
                Log.d(TAG, "manual sync: attached foreground state to running worker")
                return true
            }
        }

        if (!checkWearSyncEndpoint(appContext)) {
            Log.d(TAG, "manual sync: Wear endpoint unavailable; foreground sync not started")
            return false
        }
        val workerStartedDuringEndpointProbe = hasRunningSyncWork(appContext)
        mutex.withLock {
            setManualSyncState(SyncPhase.CONNECTING, 0f)
            if (workerStartedDuringEndpointProbe || isWorkerRunning.get()) {
                Log.d(TAG, "manual sync: attached foreground state to worker started during endpoint probe")
            } else {
                MobileSyncToWatchWorker.enqueueManual(appContext)
                Log.d(TAG, "manual sync: replaced delayed pending work and enqueued immediate mobile sync to watch")
            }
        }
        return true
    }

    internal fun onWorkerSyncAttemptSucceeded(
        appContext: Context,
        sentWorkoutStoreFingerprint: String,
        wasManualSync: Boolean
    ) {
        scope.launch {
            delay(FOLLOW_UP_ENQUEUE_DELAY_MS)
            mutex.withLock {
                setLastCompletedAutomaticFingerprint(appContext, sentWorkoutStoreFingerprint)
                if (pendingManualOverride.compareAndSet(true, false)) {
                    setPendingManualOverride(appContext, false)
                    MobileSyncToWatchWorker.enqueueManual(appContext)
                    Log.d(TAG, "after successful sync, enqueued immediate manual override")
                } else if (pendingFollowUp.compareAndSet(true, false)) {
                    setPendingFollowUp(appContext, false)
                    if (automaticSyncState.hasUnsentAutomaticState()) {
                        MobileSyncToWatchWorker.enqueue(appContext)
                        Log.d(TAG, "after successful sync, enqueued follow-up from pending")
                    } else {
                        Log.d(TAG, "after successful sync, skipped pending follow-up because latest automatic state was already sent")
                    }
                    if (wasManualSync || _manualSyncProgress.value != null) {
                        clearManualSyncState()
                    }
                } else if (wasManualSync || _manualSyncProgress.value != null) {
                    clearManualSyncState()
                }
            }
        }
    }

    internal fun onWorkerSyncAttemptWillRetry(appContext: Context): Boolean {
        clearManualSyncState()
        if (pendingManualOverride.compareAndSet(true, false)) {
            setPendingManualOverride(appContext, false)
            scope.launch {
                delay(FOLLOW_UP_ENQUEUE_DELAY_MS)
                MobileSyncToWatchWorker.enqueueManual(appContext)
                Log.d(TAG, "worker failed; replaced retry backoff with immediate manual override")
            }
            return false
        }
        setPendingFollowUp(appContext, false)
        Log.d(TAG, "worker will retry; cleared pending (retry sends latest state)")
        return true
    }

    internal fun updateManualSyncState(phase: SyncPhase, progress: Float) {
        if (_manualSyncUiState.value != null) {
            setManualSyncState(phase, progress)
        }
    }

    internal fun onManualSyncFailed() {
        clearManualSyncState()
    }

    private fun setManualSyncState(phase: SyncPhase, progress: Float) {
        val normalizedProgress = progress.coerceIn(0f, 1f)
        _manualSyncProgress.value = normalizedProgress
        _manualSyncUiState.value = ManualSyncUiState(phase, normalizedProgress)
    }

    private fun clearManualSyncState() {
        _manualSyncProgress.value = null
        _manualSyncUiState.value = null
    }
}
