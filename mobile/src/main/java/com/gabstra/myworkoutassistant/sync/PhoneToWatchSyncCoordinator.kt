package com.gabstra.myworkoutassistant.sync

import android.content.Context
import android.util.Log
import androidx.work.WorkInfo
import androidx.work.WorkManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Coordinates automatic phone→Wear sync after phone-originated persistence:
 * debounced enqueue when idle, a single replaceable pending follow-up while sync is running,
 * and one follow-up enqueue after a successful sync when pending was set.
 */
object PhoneToWatchSyncCoordinator {
    private const val TAG = "PhoneToWatchSyncCoordinator"
    private const val DEBOUNCE_MS = 2_000L
    /** Defer follow-up enqueue until [MobileSyncToWatchWorker.doWork] has returned so WorkManager is not still RUNNING. */
    private const val FOLLOW_UP_ENQUEUE_DELAY_MS = 100L
    private const val PREFS_NAME = "phone_to_watch_sync_coordinator"
    private const val KEY_PENDING_FOLLOW_UP = "pending_follow_up_sync"

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val mutex = Mutex()
    private var debounceJob: Job? = null
    private val pendingFollowUp = AtomicBoolean(false)
    private val isWorkerRunning = AtomicBoolean(false)

    private var installed = false

    private fun setPendingFollowUp(context: Context, pending: Boolean) {
        pendingFollowUp.set(pending)
        context.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit()
            .putBoolean(KEY_PENDING_FOLLOW_UP, pending)
            .apply()
    }

    /**
     * Subscribes to WorkManager state for the mobile sync worker. Call once from [android.app.Activity.onCreate] or equivalent.
     */
    fun install(context: Context) {
        if (installed) return
        installed = true
        val appContext = context.applicationContext
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
            if (prefs.getBoolean(KEY_PENDING_FOLLOW_UP, false)) {
                mutex.withLock {
                    setPendingFollowUp(appContext, false)
                }
                MobileSyncToWatchWorker.enqueue(appContext)
                Log.d(TAG, "install: had persisted pending follow-up, enqueued mobile sync to watch")
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
        mutex.withLock {
            if (isWorkerRunning.get()) {
                setPendingFollowUp(appContext, true)
                Log.d(TAG, "onPhoneDataPersisted: sync running, pending follow-up set")
                return
            }
            debounceJob?.cancel()
            val scheduledJob = scope.launch {
                delay(DEBOUNCE_MS)
                val currentJob = currentCoroutineContext()[Job]
                mutex.withLock {
                    try {
                        if (PhoneSyncToWatchSuppressor.shouldSuppressPhoneToWatchSync()) {
                            return@withLock
                        }
                        if (isWorkerRunning.get()) {
                            setPendingFollowUp(appContext, true)
                            Log.d(TAG, "debounce completed while sync running, pending follow-up set")
                        } else {
                            MobileSyncToWatchWorker.enqueue(appContext)
                            Log.d(TAG, "debounce completed, enqueued mobile sync to watch")
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
    suspend fun requestManualSyncToWatch(context: Context) {
        val appContext = context.applicationContext
        mutex.withLock {
            debounceJob?.cancel()
            debounceJob = null
            if (isWorkerRunning.get()) {
                setPendingFollowUp(appContext, true)
                Log.d(TAG, "manual sync: worker running, pending follow-up set")
            } else {
                MobileSyncToWatchWorker.enqueue(appContext)
                Log.d(TAG, "manual sync: enqueued mobile sync to watch")
            }
        }
    }

    internal fun onWorkerSyncAttemptSucceeded(appContext: Context) {
        scope.launch {
            delay(FOLLOW_UP_ENQUEUE_DELAY_MS)
            mutex.withLock {
                if (pendingFollowUp.compareAndSet(true, false)) {
                    setPendingFollowUp(appContext, false)
                    MobileSyncToWatchWorker.enqueue(appContext)
                    Log.d(TAG, "after successful sync, enqueued follow-up from pending")
                }
            }
        }
    }

    internal fun onWorkerSyncAttemptWillRetry(appContext: Context) {
        setPendingFollowUp(appContext, false)
        Log.d(TAG, "worker will retry; cleared pending (retry sends latest state)")
    }
}
