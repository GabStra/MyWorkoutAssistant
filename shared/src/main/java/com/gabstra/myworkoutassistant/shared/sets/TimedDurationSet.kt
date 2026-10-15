package com.gabstra.myworkoutassistant.shared.sets

import com.gabstra.myworkoutassistant.shared.workout.progression.DurationProgressionSnapshot

import java.util.UUID

data class TimedDurationSet(
    override val id: UUID,
    val timeInMillis: Int,
    val autoStart:Boolean,
    val autoStop:Boolean,
    override val shouldReapplyHistoryToSet: Boolean = true,
    val targetWeight: Double? = null,
    val targetDistanceMeters: Double? = null,
    val targetCalories: Double? = null,
    val durationProgressionSnapshot: DurationProgressionSnapshot? = null
) : Set(id, shouldReapplyHistoryToSet)
