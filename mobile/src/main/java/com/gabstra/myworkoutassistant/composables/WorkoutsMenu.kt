package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.gabstra.myworkoutassistant.shared.Orange
import com.google.accompanist.permissions.ExperimentalPermissionsApi

@OptIn(ExperimentalPermissionsApi::class)
@Composable
fun WorkoutsMenu(
    onSyncClick: () -> Unit,
    onBackupClick: () -> Unit,
    onRestoreClick: () -> Unit,
    onImportWorkoutsClick: () -> Unit,
    onOpenSettingsClick: () -> Unit,
    onClearAllHistories: () -> Unit,
    onSyncWithHealthConnectClick: () -> Unit,
    onExportWorkouts: () -> Unit,
    onExportWorkoutPlan: () -> Unit,
    onExportEquipment: () -> Unit,
    onClearAllExerciseInfo: () -> Unit,
    onViewErrorLogs: () -> Unit,
    onMenuItemClick: () -> Unit = {},
) {
    var showClearHistoryDialog by remember { mutableStateOf(false) }
    var showClearExerciseInfoDialog by remember { mutableStateOf(false) }

    val scrollState = rememberScrollState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(scrollState)
            .padding(vertical = 8.dp)
    ) {
        MenuSectionHeader("Settings", showDivider = false)
        WorkoutsMenuItem(
            label = "Settings",
            onClick = {
                onOpenSettingsClick()
                onMenuItemClick()
            }
        )

        MenuSectionHeader("Sync")
        WorkoutsMenuItem(
            label = "Sync with Watch",
            onClick = {
                onSyncClick()
                onMenuItemClick()
            }
        )
        WorkoutsMenuItem(
            label = "Sync with Health Connect",
            onClick = {
                onSyncWithHealthConnectClick()
                onMenuItemClick()
            }
        )

        MenuSectionHeader("Export")
        WorkoutsMenuItem(
            label = "Export Workouts",
            onClick = {
                onExportWorkouts()
                onMenuItemClick()
            }
        )
        WorkoutsMenuItem(
            label = "Export Workout Plan (Markdown)",
            onClick = {
                onExportWorkoutPlan()
                onMenuItemClick()
            }
        )
        WorkoutsMenuItem(
            label = "Export Equipment (JSON)",
            onClick = {
                onExportEquipment()
                onMenuItemClick()
            }
        )

        MenuSectionHeader("Data")
        WorkoutsMenuItem(
            label = "Save Backup",
            onClick = {
                onBackupClick()
                onMenuItemClick()
            }
        )
        WorkoutsMenuItem(
            label = "Restore Backup",
            onClick = {
                onRestoreClick()
                onMenuItemClick()
            }
        )
        WorkoutsMenuItem(
            label = "Import Workout Plan",
            onClick = {
                onImportWorkoutsClick()
                onMenuItemClick()
            }
        )

        MenuSectionHeader("Maintenance")
        WorkoutsMenuItem(
            label = "Clear workout history",
            onClick = {
                showClearHistoryDialog = true
                onMenuItemClick()
            }
        )
//        WorkoutsMenuItem(
//            label = "Clear all exercise info",
//            onClick = {
//                showClearExerciseInfoDialog = true
//                onMenuItemClick()
//            }
//        )

        MenuSectionHeader("Diagnostics")
        WorkoutsMenuItem(
            label = "View Error Logs",
            onClick = {
                onViewErrorLogs()
                onMenuItemClick()
            }
        )
    }

    ConfirmationDialog(
        show = showClearHistoryDialog,
        title = "Clear Workout History",
        message = "Are you sure you want to clear all workout history? This action cannot be undone.",
        confirmText = "Clear",
        isDestructive = true,
        onConfirm = {
            onClearAllHistories()
            showClearHistoryDialog = false
        },
        onDismiss = {
            showClearHistoryDialog = false
        }
    )

    ConfirmationDialog(
        show = showClearExerciseInfoDialog,
        title = "Clear Exercise Info",
        message = "Are you sure you want to clear all exercise info? This action cannot be undone.",
        confirmText = "Clear",
        isDestructive = true,
        onConfirm = {
            onClearAllExerciseInfo()
            showClearExerciseInfoDialog = false
        },
        onDismiss = {
            showClearExerciseInfoDialog = false
        }
    )
}

@Composable
private fun WorkoutsMenuItem(
    label: String,
    onClick: () -> Unit
) {
    AppDropdownMenuItem(
        text = {
            Text(
                text = label,
                fontWeight = FontWeight.Normal
            )
        },
        onClick = onClick
    )
}

@Composable
fun MenuSectionHeader(title: String, showDivider: Boolean = true) {
    val dividerColor = LocalContentColor.current.copy(alpha = 0.45f)
    if (showDivider) {
        HorizontalDivider(color = dividerColor)
    }
    Text(
        text = title,
        color = Orange,
        style = MaterialTheme.typography.labelSmall.copy(
            fontWeight = FontWeight.SemiBold,
            letterSpacing = 0.8.sp
        ),
        modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp)
    )
}
