package com.gabstra.myworkoutassistant.data

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * Debouncer utility for batching sync operations from Wear OS to Mobile.
 * Cancels previous sync jobs and creates new ones with a delay, effectively
 * debouncing rapid consecutive sync requests.
 *
 * @param scope The coroutine scope to launch sync operations in
 * @param debounceDelayMs Delay in milliseconds before executing the sync (default: 1000ms)
 */
class WearOSSyncDebouncer(
    private val scope: CoroutineScope,
    private val debounceDelayMs: Long = 1000L
) {
    private val mutex = Mutex()
    private var syncJob: Job? = null
    private var pendingSyncAction: (suspend () -> Unit)? = null

    /**
     * Schedules a debounced sync operation. If a sync is already scheduled,
     * it cancels the previous one and schedules a new one with the delay.
     *
     * @param syncAction The suspend function to execute after the debounce delay
     */
    suspend fun schedule(syncAction: suspend () -> Unit) {
        mutex.withLock {
            // Cancel existing job if any
            syncJob?.cancel()
            
            // Store the latest sync action
            pendingSyncAction = syncAction
            
            // Create new job with delay
            syncJob = scope.launch {
                delay(debounceDelayMs)
                mutex.withLock {
                    // Re-check if this job is still current (not cancelled and not replaced)
                    if (syncJob?.isActive == true && pendingSyncAction != null) {
                        val action = pendingSyncAction
                        pendingSyncAction = null
                        action?.invoke()
                    }
                }
            }
        }
    }

    /**
     * Immediately executes any pending sync operation and cancels the debounce timer.
     * If no sync is pending, this is a no-op.
     */
    suspend fun flush() {
        mutex.withLock {
            syncJob?.cancel()
            val action = pendingSyncAction
            pendingSyncAction = null
            if (action != null) {
                action()
            }
        }
    }

    /**
     * Cancels any pending sync operation without executing it.
     */
    suspend fun cancel() {
        mutex.withLock {
            syncJob?.cancel()
            pendingSyncAction = null
        }
    }
}
