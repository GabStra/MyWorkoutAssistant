package com.gabstra.myworkoutassistant.shared

import java.time.LocalDateTime

const val APP_BACKUP_ARCHIVE_FORMAT = "myworkoutassistant.incrementalBackup"
const val APP_BACKUP_ARCHIVE_FORMAT_VERSION = 1

data class AppBackupArchive(
    val format: String = APP_BACKUP_ARCHIVE_FORMAT,
    val formatVersion: Int = APP_BACKUP_ARCHIVE_FORMAT_VERSION,
    val baseBackup: AppBackup,
    val baseHash: String,
    val createdAt: LocalDateTime,
    val lastCompactedAt: LocalDateTime,
    val deltas: List<AppBackupDelta> = emptyList(),
)

data class AppBackupDelta(
    val createdAt: LocalDateTime,
    val previousHash: String,
    val resultHash: String,
    val workoutStore: WorkoutStore? = null,
    val workoutHistories: BackupListDelta<WorkoutHistory> = BackupListDelta(),
    val setHistories: BackupListDelta<SetHistory> = BackupListDelta(),
    val restHistories: BackupListDelta<RestHistory> = BackupListDelta(),
    val exerciseInfos: BackupListDelta<ExerciseInfo> = BackupListDelta(),
    val workoutSchedules: BackupListDelta<WorkoutSchedule> = BackupListDelta(),
    val workoutRecords: BackupListDelta<WorkoutRecord> = BackupListDelta(),
    val exerciseSessionProgressions: BackupListDelta<ExerciseSessionProgression> = BackupListDelta(),
    val errorLogs: BackupListDelta<ErrorLog> = BackupListDelta(),
) {
    fun isEmpty(): Boolean =
        workoutStore == null &&
            workoutHistories.isEmpty() &&
            setHistories.isEmpty() &&
            restHistories.isEmpty() &&
            exerciseInfos.isEmpty() &&
            workoutSchedules.isEmpty() &&
            workoutRecords.isEmpty() &&
            exerciseSessionProgressions.isEmpty() &&
            errorLogs.isEmpty()
}

data class BackupListDelta<T>(
    val upserts: List<T> = emptyList(),
    val deletes: List<String> = emptyList(),
) {
    fun isEmpty(): Boolean = upserts.isEmpty() && deletes.isEmpty()
}

