package com.gabstra.myworkoutassistant.shared.setdata

import com.gabstra.myworkoutassistant.shared.workout.progression.DurationProgressionSnapshot

data class TimedDurationSetData(
    val startTimer: Int,
    val endTimer: Int,
    val autoStart: Boolean,
    val autoStop: Boolean,
    val hasBeenExecuted: Boolean = false,
    val actualWeight: Double? = null,
    val durationProgressionSnapshot: DurationProgressionSnapshot? = null
) : SetData()
