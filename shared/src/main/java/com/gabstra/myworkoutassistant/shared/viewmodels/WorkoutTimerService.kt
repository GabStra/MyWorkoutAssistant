package com.gabstra.myworkoutassistant.shared.viewmodels

import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.time.Duration
import java.time.LocalDateTime
import java.time.temporal.ChronoUnit
import java.util.UUID

/**
 * Service that manages workout timers independently of composable lifecycle.
 * Updates state.currentSetData.endTimer continuously so ExerciseIndicator
 * can show progress even when the set screen composable is not visible.
 */
class WorkoutTimerService(
    private val viewModelScope: CoroutineScope,
    private val isPaused: () -> Boolean
) {
    data class TimerCallbacks(
        val onTimerEnd: () -> Unit,
        val onTimerEnabled: () -> Unit,
        val onTimerDisabled: () -> Unit
    )

    private data class ActiveTimer(
        val state: WorkoutState.Set,
        val callbacks: TimerCallbacks,
        val isEndurance: Boolean // true for EnduranceSet, false for TimedDurationSet
    )

    private val activeTimers = mutableMapOf<UUID, ActiveTimer>()
    private var updateJob: Job? = null

    /**
     * Register a timer to be tracked and updated by the service.
     * The timer must have state.startTime set before calling this.
     */
    fun registerTimer(
        state: WorkoutState.Set,
        callbacks: TimerCallbacks
    ) {
        val setData = state.currentSetData
        val isEndurance = setData is EnduranceSetData
        
        if (state.startTime == null) {
            // Timer hasn't started yet, don't register
            return
        }

        activeTimers[state.set.id] = ActiveTimer(
            state = state,
            callbacks = callbacks,
            isEndurance = isEndurance
        )

        // Start update loop if not already running
        if (updateJob?.isActive != true) {
            startUpdateLoop()
        }

        // Call onTimerEnabled when registering
        callbacks.onTimerEnabled()
    }

    /**
     * Unregister a timer (e.g., when set is completed or stopped).
     */
    fun unregisterTimer(setId: UUID) {
        val timer = activeTimers.remove(setId)
        timer?.callbacks?.onTimerDisabled()
        
        // Stop update loop if no active timers
        if (activeTimers.isEmpty()) {
            updateJob?.cancel()
            updateJob = null
        }
    }

    /**
     * Unregister all timers (e.g., when workout ends).
     */
    fun unregisterAll() {
        activeTimers.values.forEach { it.callbacks.onTimerDisabled() }
        activeTimers.clear()
        updateJob?.cancel()
        updateJob = null
    }

    /**
     * Check if a timer is currently registered.
     */
    fun isTimerRegistered(setId: UUID): Boolean {
        return activeTimers.containsKey(setId)
    }

    private fun startUpdateLoop() {
        updateJob?.cancel()
        updateJob = viewModelScope.launch {
            while (isActive) {
                val now = LocalDateTime.now()
                val nextSecond = now.plusSeconds(1).truncatedTo(ChronoUnit.SECONDS)
                delay(Duration.between(now, nextSecond).toMillis())

                if (!isActive) break

                // Skip updates if paused
                if (isPaused()) {
                    delay(1000)
                    continue
                }

                // Update all active timers
                val timersToRemove = mutableListOf<UUID>()
                activeTimers.values.forEach { timer ->
                    val completed = updateTimerProgress(timer)
                    if (completed) {
                        timersToRemove.add(timer.state.set.id)
                    }
                }

                // Remove completed timers
                timersToRemove.forEach { setId ->
                    val timer = activeTimers.remove(setId)
                    timer?.callbacks?.onTimerEnd?.invoke()
                    timer?.callbacks?.onTimerDisabled?.invoke()
                }

                // Stop loop if no active timers
                if (activeTimers.isEmpty()) {
                    break
                }
            }
        }
    }

    /**
     * Update timer progress for a single timer.
     * @return true if timer completed, false otherwise
     */
    private fun updateTimerProgress(timer: ActiveTimer): Boolean {
        val state = timer.state
        val startTime = state.startTime ?: return false

        val now = LocalDateTime.now()
        val elapsedMillis = Duration.between(startTime, now).toMillis().toInt().coerceAtLeast(0)

        val currentSetData = state.currentSetData

        when {
            timer.isEndurance -> {
                // EnduranceSet: count up from 0
                val setData = currentSetData as? EnduranceSetData ?: return false
                val newEndTimer = elapsedMillis.coerceAtMost(setData.startTimer)
                
                // Only update if value changed to avoid unnecessary recompositions
                if (setData.endTimer != newEndTimer) {
                    state.currentSetData = setData.copy(endTimer = newEndTimer)
                }

                // Check if timer reached startTimer (for autoStop) or exceeded it
                if (newEndTimer >= setData.startTimer) {
                    if (timer.state.set.let { it is com.gabstra.myworkoutassistant.shared.sets.EnduranceSet && it.autoStop }) {
                        state.currentSetData = setData.copy(endTimer = setData.startTimer)
                        return true
                    }
                }
                return false
            }
            else -> {
                // TimedDurationSet: count down from startTimer
                val setData = currentSetData as? TimedDurationSetData ?: return false
                val remainingMillis = (setData.startTimer - elapsedMillis).coerceAtLeast(0)
                
                // Only update if value changed to avoid unnecessary recompositions
                if (setData.endTimer != remainingMillis) {
                    state.currentSetData = setData.copy(endTimer = remainingMillis)
                }

                // Timer completed when it reaches 0
                if (remainingMillis <= 0) {
                    state.currentSetData = setData.copy(endTimer = 0)
                    return true
                }
                return false
            }
        }
    }
}
