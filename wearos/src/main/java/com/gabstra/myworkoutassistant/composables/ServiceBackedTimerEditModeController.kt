package com.gabstra.myworkoutassistant.composables

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue

internal class ServiceBackedTimerEditModeController(
    private val isWorkoutPaused: () -> Boolean,
    private val isTimerRegistered: () -> Boolean,
    private val readProgressMillis: () -> Int,
    private val readMaxMillis: () -> Int,
    private val isProgressRunning: (progressMillis: Int, maxMillis: Int) -> Boolean,
    private val toElapsedMillis: (progressMillis: Int, maxMillis: Int) -> Int,
    private val applyFrozenProgressMillis: (Int) -> Unit,
    private val applyStartTimeFromElapsedMillis: (Int) -> Unit,
    private val registerTimer: () -> Unit,
    private val unregisterTimer: () -> Unit,
    private val nowMillis: () -> Long,
) {
    var isEditMode by mutableStateOf(false)
        private set

    private var wasTimerRunningBeforeEditMode by mutableStateOf(false)
    private var frozenProgressMillis by mutableIntStateOf(-1)
    private var lastInteractionTimeMillis by mutableLongStateOf(nowMillis())

    fun recordInteraction() {
        lastInteractionTimeMillis = nowMillis()
    }

    fun shouldAutoClose(timeoutMillis: Long): Boolean {
        return isEditMode && (nowMillis() - lastInteractionTimeMillis > timeoutMillis)
    }

    fun toggleEditMode() {
        updateEditMode(!isEditMode)
    }

    fun updateEditMode(enabled: Boolean) {
        if (isEditMode == enabled) return
        if (enabled) {
            pauseTimerForEditing()
            recordInteraction()
        } else {
            resumeTimerAfterEditing()
        }
        isEditMode = enabled
    }

    private fun pauseTimerForEditing() {
        val maxMillis = readMaxMillis().coerceAtLeast(0)
        val progressMillis = readProgressMillis().coerceIn(0, maxMillis)

        frozenProgressMillis = progressMillis
        applyFrozenProgressMillis(progressMillis)

        if (!isTimerRegistered()) {
            wasTimerRunningBeforeEditMode = false
            return
        }

        wasTimerRunningBeforeEditMode = isProgressRunning(progressMillis, maxMillis)
        if (wasTimerRunningBeforeEditMode) {
            unregisterTimer()
        }
    }

    private fun resumeTimerAfterEditing() {
        if (!wasTimerRunningBeforeEditMode) return

        val maxMillis = readMaxMillis().coerceAtLeast(0)
        val progressMillis = frozenProgressMillis.coerceIn(0, maxMillis)
        val elapsedMillis = toElapsedMillis(progressMillis, maxMillis).coerceIn(0, maxMillis)

        applyFrozenProgressMillis(progressMillis)
        applyStartTimeFromElapsedMillis(elapsedMillis)

        if (!isWorkoutPaused() && !isTimerRegistered()) {
            registerTimer()
        }

        wasTimerRunningBeforeEditMode = false
        frozenProgressMillis = -1
    }
}
