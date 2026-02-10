package com.gabstra.myworkoutassistant.shared

enum class BackupCleanupAction {
    RUN_CLEANUP,
    SHOW_ALL_FILES_RATIONALE,
    REQUEST_READ_STORAGE_PERMISSION
}

fun determineBackupCleanupAction(
    hasDownloadsAccess: Boolean,
    sdkInt: Int,
    allFilesApiLevel: Int = 30
): BackupCleanupAction {
    if (hasDownloadsAccess) {
        return BackupCleanupAction.RUN_CLEANUP
    }

    return if (sdkInt >= allFilesApiLevel) {
        BackupCleanupAction.SHOW_ALL_FILES_RATIONALE
    } else {
        BackupCleanupAction.REQUEST_READ_STORAGE_PERMISSION
    }
}
