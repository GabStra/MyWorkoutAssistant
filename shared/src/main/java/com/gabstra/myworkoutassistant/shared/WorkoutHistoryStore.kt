package com.gabstra.myworkoutassistant.shared

data class WorkoutHistoryStore(
    val WorkoutHistory : WorkoutHistory,
    val ExerciseHistories : List<SetHistory>,
    val ExerciseInfos : List<ExerciseInfo>
)