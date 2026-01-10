package com.gabstra.myworkoutassistant

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * Debouncer utility for batching save operations.
 * Cancels previous save jobs and creates new ones with a delay, effectively
 * debouncing rapid consecutive save requests.
 *
 * @param scope The coroutine scope to launch save operations in
 * @param debounceDelayMs Delay in milliseconds before executing the save (default: 1000ms)
 */
class WorkoutSaveDebouncer(
    private val scope: CoroutineScope,
    private val debounceDelayMs: Long = 1000L
) {
    private val mutex = Mutex()
    private var saveJob: Job? = null
    private var pendingSaveAction: (suspend () -> Unit)? = null

    /**
     * Schedules a debounced save operation. If a save is already scheduled,
     * it cancels the previous one and schedules a new one with the delay.
     *
     * @param saveAction The suspend function to execute after the debounce delay
     */
    suspend fun schedule(saveAction: suspend () -> Unit) {
        mutex.withLock {
            // Cancel existing job if any
            saveJob?.cancel()
            
            // Store the latest save action
            pendingSaveAction = saveAction
            
            // Create new job with delay
            saveJob = scope.launch {
                delay(debounceDelayMs)
                mutex.withLock {
                    // Re-check if this job is still current (not cancelled and not replaced)
                    if (saveJob?.isActive == true && pendingSaveAction != null) {
                        val action = pendingSaveAction
                        pendingSaveAction = null
                        action?.invoke()
                    }
                }
            }
        }
    }

    /**
     * Immediately executes any pending save operation and cancels the debounce timer.
     * If no save is pending, this is a no-op.
     */
    suspend fun flush() {
        mutex.withLock {
            saveJob?.cancel()
            val action = pendingSaveAction
            pendingSaveAction = null
            if (action != null) {
                action()
            }
        }
    }

    /**
     * Cancels any pending save operation without executing it.
     */
    suspend fun cancel() {
        mutex.withLock {
            saveJob?.cancel()
            pendingSaveAction = null
        }
    }
}
