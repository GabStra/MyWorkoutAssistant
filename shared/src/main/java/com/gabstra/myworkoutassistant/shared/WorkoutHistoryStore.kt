package com.gabstra.myworkoutassistant.shared

import java.time.LocalDate

data class WorkoutHistoryStore(
    val WorkoutHistory : WorkoutHistory,
    val ExerciseHistories : List<ExerciseHistory>
)