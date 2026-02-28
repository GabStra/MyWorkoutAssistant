package com.gabstra.myworkoutassistant.shared.workout.timer

import android.os.SystemClock
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.util.UUID

/**
 * Service that manages workout timers independently of composable lifecycle.
 * Updates state.currentSetData.endTimer continuously so ExerciseIndicator
 * can show progress even when the set screen composable is not visible.
 */
class WorkoutTimerService(
    private val viewModelScope: CoroutineScope,
    private val isPaused: () -> Boolean,
    private val onTimerProgressChanged: (() -> Unit)? = null,
    private val monotonicNowMs: () -> Long = { SystemClock.elapsedRealtime() }
) {
    enum class TimerType {
        ENDURANCE_SET,
        TIMED_DURATION_SET,
        REST
    }

    data class TimerUiState(
        val setId: UUID,
        val timerType: TimerType,
        val displaySeconds: Int,
        val displayMillis: Int,
        val startValue: Int,
        val isRunning: Boolean
    )

    data class TimerCallbacks(
        val onTimerEnd: () -> Unit,
        val onTimerEnabled: () -> Unit,
        val onTimerDisabled: () -> Unit
    )

    private data class ActiveTimer(
        val setState: WorkoutState.Set? = null,
        val restState: WorkoutState.Rest? = null,
        val callbacks: TimerCallbacks,
        val type: TimerType,
        var baseRealtimeMs: Long,
        var baseElapsedMs: Long
    )

    private companion object {
        const val UPDATE_INTERVAL_MS = 200L
    }

    private val activeTimers = mutableMapOf<UUID, ActiveTimer>()
    private val pausedTimers = mutableMapOf<UUID, Long>()
    private val _timerUiStates = MutableStateFlow<Map<UUID, TimerUiState>>(emptyMap())
    val timerUiStates: StateFlow<Map<UUID, TimerUiState>> = _timerUiStates.asStateFlow()
    private var updateJob: Job? = null

    fun timerUiState(setId: UUID): Flow<TimerUiState?> {
        return timerUiStates.map { it[setId] }.distinctUntilChanged()
    }

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

        val initialElapsedMs = when (setData) {
            is EnduranceSetData -> setData.endTimer.coerceIn(0, setData.startTimer).toLong()
            is TimedDurationSetData -> (setData.startTimer - setData.endTimer).coerceAtLeast(0).toLong()
            else -> 0L
        }

        activeTimers[state.set.id] = ActiveTimer(
            setState = state,
            callbacks = callbacks,
            type = if (isEndurance) TimerType.ENDURANCE_SET else TimerType.TIMED_DURATION_SET,
            baseRealtimeMs = monotonicNowMs(),
            baseElapsedMs = initialElapsedMs
        )
        publishTimerUiState(state.set.id)

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

        val initialElapsedMs = ((setData.startTimer - setData.endTimer).coerceAtLeast(0) * 1000L)

        activeTimers[state.set.id] = ActiveTimer(
            restState = state,
            callbacks = callbacks,
            type = TimerType.REST,
            baseRealtimeMs = monotonicNowMs(),
            baseElapsedMs = initialElapsedMs
        )
        publishTimerUiState(state.set.id)

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
        clearTimerUiState(setId)
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
        _timerUiStates.value = emptyMap()
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
        pausedTimers[setId] = monotonicNowMs()
        publishTimerUiState(setId)
    }

    /**
     * Resume a previously paused timer and compensate baseRealtime
     * so elapsed/remaining values continue from the paused position.
     */
    fun resumeTimer(setId: UUID) {
        val pausedAtMs = pausedTimers.remove(setId) ?: return
        val timer = activeTimers[setId] ?: return
        val pausedDurationMs = (monotonicNowMs() - pausedAtMs).coerceAtLeast(0L)
        if (pausedDurationMs <= 0L) return

        timer.baseRealtimeMs += pausedDurationMs
        publishTimerUiState(setId)
    }

    /**
     * Freeze active timers when app moves to background.
     */
    fun pauseForBackground() {
        // Keep timers running while backgrounded for workout UX consistency.
    }

    /**
     * Resume timers after app returns to foreground.
     */
    fun resumeFromBackground() {
        // No compensation needed because timers are not paused in background.
    }

    private fun startUpdateLoop() {
        updateJob?.cancel()
        updateJob = viewModelScope.launch {
            while (isActive) {
                delay(UPDATE_INTERVAL_MS)

                if (!isActive) break

                // Skip updates if paused
                if (isPaused()) {
                    continue
                }

                // Update all active timers
                val updateNowMs = monotonicNowMs()
                val timersToRemove = mutableListOf<UUID>()
                activeTimers.forEach { (timerId, timer) ->
                    if (pausedTimers.containsKey(timerId)) {
                        publishTimerUiState(timerId)
                        return@forEach
                    }

                    val completed = updateTimerProgress(timer, nowMs = updateNowMs)
                    publishTimerUiState(timerId)
                    if (completed) {
                        timersToRemove.add(timerId)
                    }
                }

                // Remove completed timers
                timersToRemove.forEach { setId ->
                    val timer = activeTimers.remove(setId)
                    pausedTimers.remove(setId)
                    clearTimerUiState(setId)
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
    private fun updateTimerProgress(timer: ActiveTimer, nowMs: Long): Boolean {
        val elapsedMs = (timer.baseElapsedMs + (nowMs - timer.baseRealtimeMs)).coerceAtLeast(0L)

        when (timer.type) {
            TimerType.ENDURANCE_SET -> {
                val state = timer.setState ?: return false
                val currentSetData = state.currentSetData
                // EnduranceSet: count up from 0
                val setData = currentSetData as? EnduranceSetData ?: return false
                val newEndTimer = elapsedMs.coerceAtMost(setData.startTimer.toLong()).toInt()
                val previousSeconds = (setData.endTimer / 1000).coerceAtLeast(0)
                val nextSeconds = (newEndTimer / 1000).coerceAtLeast(0)
                val reachedLimit = newEndTimer >= setData.startTimer

                // Only update if value changed to avoid unnecessary recompositions
                if (setData.endTimer != newEndTimer && (nextSeconds != previousSeconds || reachedLimit)) {
                    state.currentSetData = setData.copy(endTimer = newEndTimer)
                    onTimerProgressChanged?.invoke()
                }

                // Check if timer reached startTimer (for autoStop) or exceeded it
                if (reachedLimit) {
                    if (state.set.let { it is com.gabstra.myworkoutassistant.shared.sets.EnduranceSet && it.autoStop }) {
                        state.currentSetData = setData.copy(endTimer = setData.startTimer)
                        return true
                    }
                }
                return false
            }

            TimerType.TIMED_DURATION_SET -> {
                val state = timer.setState ?: return false
                val currentSetData = state.currentSetData
                // TimedDurationSet: count down from startTimer
                val setData = currentSetData as? TimedDurationSetData ?: return false
                val remainingMillis = (setData.startTimer.toLong() - elapsedMs).coerceAtLeast(0L).toInt()
                val previousSeconds = (setData.endTimer / 1000).coerceAtLeast(0)
                val nextSeconds = (remainingMillis / 1000).coerceAtLeast(0)

                // Only update if value changed to avoid unnecessary recompositions
                if (setData.endTimer != remainingMillis && (nextSeconds != previousSeconds || remainingMillis == 0)) {
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
                val currentSetData = state.currentSetData
                val setData = currentSetData as? RestSetData ?: return false
                val elapsedSeconds = (elapsedMs / 1000L).toInt().coerceAtLeast(0)
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

    private fun publishTimerUiState(setId: UUID) {
        val timer = activeTimers[setId] ?: return
        val uiState = buildTimerUiState(setId, timer) ?: return
        val current = _timerUiStates.value[setId]
        if (current == uiState) return

        _timerUiStates.value = _timerUiStates.value.toMutableMap().apply {
            this[setId] = uiState
        }
    }

    private fun clearTimerUiState(setId: UUID) {
        if (!_timerUiStates.value.containsKey(setId)) return
        _timerUiStates.value = _timerUiStates.value.toMutableMap().apply {
            remove(setId)
        }
    }

    private fun buildTimerUiState(setId: UUID, timer: ActiveTimer): TimerUiState? {
        val isRunning = !pausedTimers.containsKey(setId) && !isPaused()
        return when (timer.type) {
            TimerType.TIMED_DURATION_SET -> {
                val setData = timer.setState?.currentSetData as? TimedDurationSetData ?: return null
                TimerUiState(
                    setId = setId,
                    timerType = TimerType.TIMED_DURATION_SET,
                    displaySeconds = (setData.endTimer / 1000).coerceAtLeast(0),
                    displayMillis = setData.endTimer.coerceAtLeast(0),
                    startValue = setData.startTimer,
                    isRunning = isRunning
                )
            }

            TimerType.ENDURANCE_SET -> {
                val setData = timer.setState?.currentSetData as? EnduranceSetData ?: return null
                TimerUiState(
                    setId = setId,
                    timerType = TimerType.ENDURANCE_SET,
                    displaySeconds = (setData.endTimer / 1000).coerceAtLeast(0),
                    displayMillis = setData.endTimer.coerceAtLeast(0),
                    startValue = setData.startTimer,
                    isRunning = isRunning
                )
            }

            TimerType.REST -> {
                val setData = timer.restState?.currentSetData as? RestSetData ?: return null
                TimerUiState(
                    setId = setId,
                    timerType = TimerType.REST,
                    displaySeconds = setData.endTimer.coerceAtLeast(0),
                    displayMillis = setData.endTimer.coerceAtLeast(0) * 1000,
                    startValue = setData.startTimer,
                    isRunning = isRunning
                )
            }
        }
    }
}
