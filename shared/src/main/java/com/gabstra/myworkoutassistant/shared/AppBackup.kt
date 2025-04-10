package com.gabstra.myworkoutassistant.shared

data class AppBackup(
    val WorkoutStore: WorkoutStore,
    val WorkoutHistories: List<WorkoutHistory>,
    val SetHistories: List<SetHistory>,
    val ExerciseInfos: List<ExerciseInfo>,
    val WorkoutSchedules: List<WorkoutSchedule>,
    val WorkoutRecords: List<WorkoutRecord>,
)
