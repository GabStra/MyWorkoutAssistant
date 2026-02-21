package com.gabstra.myworkoutassistant.shared.workout.recovery

import java.time.LocalDateTime

/**
 * UI state for the recovery prompt (process-death resume dialog).
 * Platform-agnostic data; platforms use it to render their recovery dialog.
 */
data class RecoveryPromptUiState(
    val displayName: String = "",
    val workoutStartTime: LocalDateTime? = null,
    val showTimerOptions: Boolean = false,
    val showCalibrationOptions: Boolean = false
) {
    val showResumeButton: Boolean
        get() = !showTimerOptions && !showCalibrationOptions
}
