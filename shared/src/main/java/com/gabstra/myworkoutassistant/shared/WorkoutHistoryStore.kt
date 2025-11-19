package com.gabstra.myworkoutassistant.shared

data class WorkoutHistoryStore(
    val WorkoutHistory : WorkoutHistory,
    val SetHistories : List<SetHistory>,
    val ExerciseInfos : List<ExerciseInfo>,
    val WorkoutRecord : WorkoutRecord?,
    val ExerciseSessionProgressions : List<ExerciseSessionProgression>,
    val ErrorLogs: List<ErrorLog> = emptyList()
)