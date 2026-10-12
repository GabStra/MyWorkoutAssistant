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
    /** Global AI-features switch; null in backups created before insights settings were exported. */
    val MobileLlmEnabled: Boolean? = null,
    /** Selected insights transport ("LOCAL"/"REMOTE"); null leaves the current setting untouched on restore. */
    val WorkoutInsightsMode: String? = null,
    /** Hosted OpenAI-compatible endpoint used by remote insights; blank fields mean unset. */
    val RemoteInsightsBaseUrl: String? = null,
    val RemoteInsightsApiKey: String? = null,
    val RemoteInsightsModel: String? = null,
    /** User insight preferences appended to insight and chat requests. */
    val WorkoutInsightsCustomInstructions: String? = null,
)

data class ExerciseMovementBackup(
    val movementRef: ExerciseMovementRef,
    val json: String? = null,
    val compressedJsonBase64: String? = null,
    val compression: String? = null,
) {
    companion object {
        const val COMPRESSION_GZIP_BASE64 = "gzip+base64"
    }
}
