package com.gabstra.myworkoutassistant.shared.workout.ui

import com.gabstra.myworkoutassistant.shared.workout.model.WorkoutSessionStatus
import java.time.LocalDateTime

data class WorkoutResumeInfo(
    val exerciseName: String,
    val setNumber: Int,
    val startedAt: LocalDateTime?,
    val sessionStatus: WorkoutSessionStatus,
    val lastActiveSyncAt: LocalDateTime?,
)
