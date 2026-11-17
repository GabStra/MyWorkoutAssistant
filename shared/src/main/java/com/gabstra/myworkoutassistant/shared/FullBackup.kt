package com.gabstra.myworkoutassistant.shared


const val FULL_BACKUP_FORMAT = "myworkoutassistant.fullBackup"
const val FULL_BACKUP_FORMAT_VERSION = 1

/**
 * One profile inside a [FullBackup]: its personal settings and its own history tables.
 *
 * The store inside [backup] holds only the personal half; the exercise library, workouts,
 * equipment and plans live once in [FullBackup.sharedStore].
 */
data class ProfileBackup(
    val profileId: String,
    val profileName: String,
    val backup: AppBackup,
)

/** A sensor recording, gzip+base64 so the JSON stays compact. */
data class MotionCaptureFileBackup(
    val relativePath: String,
    val gzipBase64: String,
)

/** Device-wide preferences that are not per profile. */
data class FullBackupSettings(
    val mobileLlmEnabled: Boolean? = null,
    val workoutInsightsMode: String? = null,
    val remoteBaseUrl: String? = null,
    val remoteApiKey: String? = null,
    val remoteModel: String? = null,
    val customInstructions: String? = null,
    val alertSoundEnabled: Boolean? = null,
    val healthConnectProfileId: String? = null,
)

/**
 * Everything needed to rebuild this install: the shared content once, every profile with its
 * own history, the shared exercise movement payloads, device-wide settings, and sensor
 * recordings.
 */
data class FullBackup(
    val format: String = FULL_BACKUP_FORMAT,
    val formatVersion: Int = FULL_BACKUP_FORMAT_VERSION,
    val createdAtEpochMs: Long = 0L,
    val sharedStore: WorkoutStore,
    val activeProfileId: String? = null,
    val profiles: List<ProfileBackup> = emptyList(),
    val exerciseMovements: List<ExerciseMovementBackup> = emptyList(),
    val settings: FullBackupSettings? = null,
    val motionCaptureFiles: List<MotionCaptureFileBackup> = emptyList(),
)

fun fromFullBackupToJSON(fullBackup: FullBackup): String = backupGson().toJson(fullBackup)

fun fromJSONToFullBackup(json: String): FullBackup =
    backupGson().fromJson(json, FullBackup::class.java)
