package com.gabstra.myworkoutassistant.shared.workout.timer

import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData

fun EnduranceSetData.canResumeRunningEnduranceTimer(autoStop: Boolean): Boolean {
    if (endTimer <= 0 || hasBeenExecuted) {
        return false
    }
    return !autoStop || endTimer < startTimer
}

fun EnduranceSetData.elapsedMillisForEnduranceTimer(): Int = endTimer.coerceAtLeast(0)
