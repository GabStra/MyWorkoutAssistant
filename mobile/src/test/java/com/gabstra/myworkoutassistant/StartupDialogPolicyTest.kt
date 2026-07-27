package com.gabstra.myworkoutassistant

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class StartupDialogPolicyTest {

    @Test
    fun `permission dialog waits until restore and sync are finished`() {
        assertFalse(
            shouldShowStartupPrerequisitesDialog(
                hasHealthPermissions = false,
                deferHealthPermissionPrompt = false,
                isRestorePromptVisible = true,
                isRestoringBackup = false,
                isSyncingWithWatch = false,
            )
        )
        assertFalse(
            shouldShowStartupPrerequisitesDialog(
                hasHealthPermissions = false,
                deferHealthPermissionPrompt = false,
                isRestorePromptVisible = false,
                isRestoringBackup = true,
                isSyncingWithWatch = false,
            )
        )
        assertFalse(
            shouldShowStartupPrerequisitesDialog(
                hasHealthPermissions = false,
                deferHealthPermissionPrompt = false,
                isRestorePromptVisible = false,
                isRestoringBackup = false,
                isSyncingWithWatch = true,
            )
        )
        assertTrue(
            shouldShowStartupPrerequisitesDialog(
                hasHealthPermissions = false,
                deferHealthPermissionPrompt = false,
                isRestorePromptVisible = false,
                isRestoringBackup = false,
                isSyncingWithWatch = false,
            )
        )
    }

    @Test
    fun `permission dialog stays hidden when deferred or already granted`() {
        assertFalse(
            shouldShowStartupPrerequisitesDialog(
                hasHealthPermissions = false,
                deferHealthPermissionPrompt = true,
                isRestorePromptVisible = false,
                isRestoringBackup = false,
                isSyncingWithWatch = false,
            )
        )
        assertFalse(
            shouldShowStartupPrerequisitesDialog(
                hasHealthPermissions = true,
                deferHealthPermissionPrompt = false,
                isRestorePromptVisible = false,
                isRestoringBackup = false,
                isSyncingWithWatch = false,
            )
        )
    }
}
