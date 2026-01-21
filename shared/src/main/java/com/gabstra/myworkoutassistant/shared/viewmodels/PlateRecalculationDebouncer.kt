package com.gabstra.myworkoutassistant.shared.viewmodels

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * Debouncer utility for batching plate recalculation operations.
 * Cancels previous recalculation jobs and creates new ones with a delay, effectively
 * debouncing rapid consecutive recalculation requests.
 *
 * @param scope The coroutine scope to launch recalculation operations in
 * @param debounceDelayMs Delay in milliseconds before executing the recalculation (default: 400ms)
 */
class PlateRecalculationDebouncer(
    private val scope: CoroutineScope,
    private val debounceDelayMs: Long = 400L
) {
    private val mutex = Mutex()
    private var recalculationJob: Job? = null
    private var pendingRecalculationAction: (suspend () -> Unit)? = null

    /**
     * Schedules a debounced recalculation operation. If a recalculation is already scheduled,
     * it cancels the previous one and schedules a new one with the delay.
     *
     * @param recalculationAction The suspend function to execute after the debounce delay
     */
    suspend fun schedule(recalculationAction: suspend () -> Unit) {
        mutex.withLock {
            // Cancel existing job if any
            recalculationJob?.cancel()
            
            // Store the latest recalculation action
            pendingRecalculationAction = recalculationAction
            
            // Create new job with delay
            recalculationJob = scope.launch {
                delay(debounceDelayMs)
                mutex.withLock {
                    // Re-check if this job is still current (not cancelled and not replaced)
                    if (recalculationJob?.isActive == true && pendingRecalculationAction != null) {
                        val action = pendingRecalculationAction
                        pendingRecalculationAction = null
                        action?.invoke()
                    }
                }
            }
        }
    }

    /**
     * Immediately executes any pending recalculation operation and cancels the debounce timer.
     * If no recalculation is pending, this is a no-op.
     */
    suspend fun flush() {
        mutex.withLock {
            recalculationJob?.cancel()
            val action = pendingRecalculationAction
            pendingRecalculationAction = null
            if (action != null) {
                action()
            }
        }
    }

    /**
     * Cancels any pending recalculation operation without executing it.
     */
    suspend fun cancel() {
        mutex.withLock {
            recalculationJob?.cancel()
            pendingRecalculationAction = null
        }
    }
}
