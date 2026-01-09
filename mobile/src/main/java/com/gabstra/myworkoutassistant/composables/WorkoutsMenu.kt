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
import com.gabstra.myworkoutassistant.shared.DarkOrange
import com.gabstra.myworkoutassistant.workout.CustomDialogYesOnLongPress
import com.google.accompanist.permissions.ExperimentalPermissionsApi

@OptIn(ExperimentalPermissionsApi::class)
@Composable
fun WorkoutsMenu(
    onSyncClick: () -> Unit,
    onBackupClick: () -> Unit,
    onRestoreClick: () -> Unit,
    onImportWorkoutsClick: () -> Unit,
    onOpenSettingsClick: () -> Unit,
    onClearUnfinishedWorkouts: () -> Unit,
    onClearAllHistories: () -> Unit,
    onSyncWithHealthConnectClick: () -> Unit,
    onExportWorkouts: () -> Unit,
    onExportWorkoutPlan: () -> Unit,
    onClearAllExerciseInfo: () -> Unit,
    onViewErrorLogs: () -> Unit,
    onMenuItemClick: () -> Unit = {},
) {
    var showClearIncompleteDialog by remember { mutableStateOf(false) }
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
        AppDropdownMenuItem(
            text = { Text("Settings") },
            onClick = {
                onOpenSettingsClick()
                onMenuItemClick()
            }
        )

        MenuSectionHeader("Sync")
        AppDropdownMenuItem(
            text = { Text("Sync with Watch") },
            onClick = {
                onSyncClick()
                onMenuItemClick()
            }
        )
        AppDropdownMenuItem(
            text = { Text("Sync with Health Connect") },
            onClick = {
                onSyncWithHealthConnectClick()
                onMenuItemClick()
            }
        )

        MenuSectionHeader("Data")
        AppDropdownMenuItem(
            text = { Text("Export Workouts") },
            onClick = {
                onExportWorkouts()
                onMenuItemClick()
            }
        )
        AppDropdownMenuItem(
            text = { Text("Export Workout Plan (Markdown)") },
            onClick = {
                onExportWorkoutPlan()
                onMenuItemClick()
            }
        )
        AppDropdownMenuItem(
            text = { Text("Save Backup") },
            onClick = {
                onBackupClick()
                onMenuItemClick()
            }
        )
        AppDropdownMenuItem(
            text = { Text("Restore Backup") },
            onClick = {
                onRestoreClick()
                onMenuItemClick()
            }
        )
        AppDropdownMenuItem(
            text = { Text("Import Workout Plan") },
            onClick = {
                onImportWorkoutsClick()
                onMenuItemClick()
            }
        )

        MenuSectionHeader("Maintenance")
        AppDropdownMenuItem(
            text = { Text("Clear incomplete workouts") },
            onClick = {
                showClearIncompleteDialog = true
                onMenuItemClick()
            }
        )
        AppDropdownMenuItem(
            text = { Text("Clear workout history") },
            onClick = {
                showClearHistoryDialog = true
                onMenuItemClick()
            }
        )
        AppDropdownMenuItem(
            text = { Text("Clear all exercise info") },
            onClick = {
                showClearExerciseInfoDialog = true
                onMenuItemClick()
            }
        )

        MenuSectionHeader("Diagnostics")
        AppDropdownMenuItem(
            text = { Text("View Error Logs") },
            onClick = {
                onViewErrorLogs()
                onMenuItemClick()
            }
        )
    }

    CustomDialogYesOnLongPress(
        show = showClearIncompleteDialog,
        title = "Clear All Incomplete Workouts",
        message = "Are you sure you want to clear all incomplete workouts? This action cannot be undone.",
        handleYesClick = {
            onClearUnfinishedWorkouts()
            showClearIncompleteDialog = false
        },
        handleNoClick = {
            showClearIncompleteDialog = false
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            showClearIncompleteDialog = false
        }
    )

    CustomDialogYesOnLongPress(
        show = showClearHistoryDialog,
        title = "Clear Workout History",
        message = "Are you sure you want to clear all workout history? This action cannot be undone.",
        handleYesClick = {
            onClearAllHistories()
            showClearHistoryDialog = false
        },
        handleNoClick = {
            showClearHistoryDialog = false
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            showClearHistoryDialog = false
        }
    )

    CustomDialogYesOnLongPress(
        show = showClearExerciseInfoDialog,
        title = "Clear Exercise Info",
        message = "Are you sure you want to clear all exercise info? This action cannot be undone.",
        handleYesClick = {
            onClearAllExerciseInfo()
            showClearExerciseInfoDialog = false
        },
        handleNoClick = {
            showClearExerciseInfoDialog = false
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            showClearExerciseInfoDialog = false
        }
    )
}

@Composable
fun MenuSectionHeader(title: String, showDivider: Boolean = true) {
    val dividerColor = LocalContentColor.current.copy(alpha = 0.2f)
    if (showDivider) {
        HorizontalDivider(color = dividerColor)
    }
    Text(
        text = title,
        color = DarkOrange,
        style = MaterialTheme.typography.labelSmall.copy(
            fontWeight = FontWeight.SemiBold,
            letterSpacing = 0.8.sp
        ),
        modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp)
    )
}
