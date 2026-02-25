package com.gabstra.myworkoutassistant.shared.workout.timer

import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
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
    private val isPaused: () -> Boolean,
    private val onTimerProgressChanged: (() -> Unit)? = null
) {
    private enum class TimerType {
        ENDURANCE_SET,
        TIMED_DURATION_SET,
        REST
    }

    data class TimerCallbacks(
        val onTimerEnd: () -> Unit,
        val onTimerEnabled: () -> Unit,
        val onTimerDisabled: () -> Unit
    )

    private data class ActiveTimer(
        val setState: WorkoutState.Set? = null,
        val restState: WorkoutState.Rest? = null,
        val callbacks: TimerCallbacks,
        val type: TimerType
    )

    private val activeTimers = mutableMapOf<UUID, ActiveTimer>()
    private val pausedTimers = mutableMapOf<UUID, LocalDateTime>()
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
            setState = state,
            callbacks = callbacks,
            type = if (isEndurance) TimerType.ENDURANCE_SET else TimerType.TIMED_DURATION_SET
        )

        // Start update loop if not already running
        if (updateJob?.isActive != true) {
            startUpdateLoop()
        }

        // Call onTimerEnabled when registering
        callbacks.onTimerEnabled()
    }

    /**
     * Register a rest timer to be tracked and updated by the service.
     * The timer must have state.startTime set before calling this.
     */
    fun registerTimer(
        state: WorkoutState.Rest,
        callbacks: TimerCallbacks
    ) {
        val setData = state.currentSetData as? RestSetData ?: return
        if (state.startTime == null || setData.endTimer <= 0) {
            // Timer hasn't started yet or is already completed.
            return
        }

        activeTimers[state.set.id] = ActiveTimer(
            restState = state,
            callbacks = callbacks,
            type = TimerType.REST
        )

        if (updateJob?.isActive != true) {
            startUpdateLoop()
        }

        callbacks.onTimerEnabled()
    }

    /**
     * Unregister a timer (e.g., when set is completed or stopped).
     */
    fun unregisterTimer(setId: UUID) {
        val timer = activeTimers.remove(setId)
        pausedTimers.remove(setId)
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
        pausedTimers.clear()
        updateJob?.cancel()
        updateJob = null
    }

    /**
     * Check if a timer is currently registered.
     */
    fun isTimerRegistered(setId: UUID): Boolean {
        return activeTimers.containsKey(setId)
    }

    /**
     * Pause an active timer without unregistering it.
     * Keeps the timer state registered and preserves callbacks.
     */
    fun pauseTimer(setId: UUID) {
        if (!activeTimers.containsKey(setId)) return
        if (pausedTimers.containsKey(setId)) return
        pausedTimers[setId] = LocalDateTime.now()
    }

    /**
     * Resume a previously paused timer and compensate startTime
     * so elapsed/remaining values continue from the paused position.
     */
    fun resumeTimer(setId: UUID) {
        val pausedAt = pausedTimers.remove(setId) ?: return
        val timer = activeTimers[setId] ?: return
        val pausedDuration = Duration.between(pausedAt, LocalDateTime.now())
        if (pausedDuration.isNegative || pausedDuration.isZero) return

        timer.setState?.startTime = timer.setState?.startTime?.plus(pausedDuration)
        timer.restState?.startTime = timer.restState?.startTime?.plus(pausedDuration)
    }

    /**
     * Freeze active timers when app moves to background.
     */
    fun pauseForBackground() {
        // Keep timers running while backgrounded for workout UX consistency.
    }

    /**
     * Resume timers after app returns to foreground by compensating startTime
     * for time spent in background.
     */
    fun resumeFromBackground() {
        // No compensation needed because timers are not paused in background.
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
                val updateNow = LocalDateTime.now()
                val timersToRemove = mutableListOf<UUID>()
                activeTimers.forEach { (timerId, timer) ->
                    if (pausedTimers.containsKey(timerId)) return@forEach
                    val completed = updateTimerProgress(timer, now = updateNow)
                    if (completed) {
                        timersToRemove.add(timerId)
                    }
                }

                // Remove completed timers
                timersToRemove.forEach { setId ->
                    val timer = activeTimers.remove(setId)
                    pausedTimers.remove(setId)
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
    private fun updateTimerProgress(timer: ActiveTimer, now: LocalDateTime): Boolean {
        when (timer.type) {
            TimerType.ENDURANCE_SET -> {
                val state = timer.setState ?: return false
                val startTime = state.startTime ?: return false
                val elapsedMillis = Duration.between(startTime, now).toMillis().toInt().coerceAtLeast(0)
                val currentSetData = state.currentSetData
                // EnduranceSet: count up from 0
                val setData = currentSetData as? EnduranceSetData ?: return false
                val newEndTimer = elapsedMillis.coerceAtMost(setData.startTimer)
                
                // Only update if value changed to avoid unnecessary recompositions
                if (setData.endTimer != newEndTimer) {
                    state.currentSetData = setData.copy(endTimer = newEndTimer)
                    onTimerProgressChanged?.invoke()
                }

                // Check if timer reached startTimer (for autoStop) or exceeded it
                if (newEndTimer >= setData.startTimer) {
                    if (state.set.let { it is com.gabstra.myworkoutassistant.shared.sets.EnduranceSet && it.autoStop }) {
                        state.currentSetData = setData.copy(endTimer = setData.startTimer)
                        return true
                    }
                }
                return false
            }
            TimerType.TIMED_DURATION_SET -> {
                val state = timer.setState ?: return false
                val startTime = state.startTime ?: return false
                val elapsedMillis = Duration.between(startTime, now).toMillis().toInt().coerceAtLeast(0)
                val currentSetData = state.currentSetData
                // TimedDurationSet: count down from startTimer
                val setData = currentSetData as? TimedDurationSetData ?: return false
                val remainingMillis = (setData.startTimer - elapsedMillis).coerceAtLeast(0)
                
                // Only update if value changed to avoid unnecessary recompositions
                if (setData.endTimer != remainingMillis) {
                    state.currentSetData = setData.copy(endTimer = remainingMillis)
                    onTimerProgressChanged?.invoke()
                }

                // Timer completed when it reaches 0
                if (remainingMillis <= 0) {
                    state.currentSetData = setData.copy(endTimer = 0)
                    return true
                }
                return false
            }
            TimerType.REST -> {
                val state = timer.restState ?: return false
                val startTime = state.startTime ?: return false
                val elapsedSeconds = Duration.between(startTime, now).seconds.toInt().coerceAtLeast(0)
                val currentSetData = state.currentSetData
                val setData = currentSetData as? RestSetData ?: return false
                val remainingSeconds = (setData.startTimer - elapsedSeconds).coerceAtLeast(0)

                if (setData.endTimer != remainingSeconds) {
                    state.currentSetData = setData.copy(endTimer = remainingSeconds)
                    onTimerProgressChanged?.invoke()
                }

                if (remainingSeconds <= 0) {
                    state.currentSetData = setData.copy(endTimer = 0)
                    return true
                }
                return false
            }
        }
    }
}

