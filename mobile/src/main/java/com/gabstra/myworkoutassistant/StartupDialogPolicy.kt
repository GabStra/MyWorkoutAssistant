package com.gabstra.myworkoutassistant

internal fun shouldShowStartupPrerequisitesDialog(
    hasHealthPermissions: Boolean,
    deferHealthPermissionPrompt: Boolean,
    isRestorePromptVisible: Boolean,
    isRestoringBackup: Boolean,
    isSyncingWithWatch: Boolean,
): Boolean = !hasHealthPermissions &&
    !deferHealthPermissionPrompt &&
    !isRestorePromptVisible &&
    !isRestoringBackup &&
    !isSyncingWithWatch
