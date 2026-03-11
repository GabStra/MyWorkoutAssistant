package com.gabstra.myworkoutassistant.shared

import java.time.LocalDate
import java.util.UUID

data class WeeklyProgressOverride(
    val weekStart: LocalDate,
    val includedWorkoutGlobalIds: List<UUID> = emptyList(),
)
