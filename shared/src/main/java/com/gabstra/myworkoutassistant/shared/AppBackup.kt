package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.motion.ExerciseMovementRef

data class AppBackup(
    val WorkoutStore: WorkoutStore,
    val WorkoutHistories: List<WorkoutHistory>,
    val SetHistories: List<SetHistory>,
    val ExerciseInfos: List<ExerciseInfo>,
    val WorkoutSchedules: List<WorkoutSchedule>,
    val WorkoutRecords: List<WorkoutRecord>,
    val ExerciseSessionProgressions: List<ExerciseSessionProgression>,
    val ErrorLogs: List<ErrorLog>? = null,
    /** Session rest intervals; omitted in older backup JSON. */
    val RestHistories: List<RestHistory>? = null,
    /** LiteRT-LM model source URI used to repopulate the local model file on restore. */
    val LiteRtLmModelSourceUri: String? = null,
    /** Wear skeleton movement JSON assets referenced by exercises in the workout store. */
    val ExerciseMovements: List<ExerciseMovementBackup>? = null,
)

data class ExerciseMovementBackup(
    val movementRef: ExerciseMovementRef,
    val json: String,
)
