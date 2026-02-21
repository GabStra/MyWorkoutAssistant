package com.gabstra.myworkoutassistant.shared.workout.recovery

/**
 * User choice for timer state when resuming after process death.
 */
enum class TimerRecoveryChoice {
    CONTINUE,
    RESTART
}

/**
 * User choice for calibration state when resuming after process death.
 */
enum class CalibrationRecoveryChoice {
    CONTINUE,
    RESTART
}

/**
 * Options selected by the user when resuming an interrupted workout after process death
 * (e.g. continue vs restart timer, continue vs restart calibration).
 */
data class RecoveryResumeOptions(
    val timerChoice: TimerRecoveryChoice = TimerRecoveryChoice.CONTINUE,
    val calibrationChoice: CalibrationRecoveryChoice = CalibrationRecoveryChoice.CONTINUE
)
