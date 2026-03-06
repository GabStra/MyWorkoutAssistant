package com.gabstra.myworkoutassistant.shared.workout.ui

import java.time.LocalDateTime

data class WorkoutResumeInfo(
    val exerciseName: String,
    val setNumber: Int,
    val startedAt: LocalDateTime?
)
