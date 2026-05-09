package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.DateRangePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.RadioButton
import androidx.compose.material3.SelectableDates
import androidx.compose.material3.Text
import androidx.compose.material3.rememberDateRangePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.gabstra.myworkoutassistant.shared.Orange
import com.gabstra.myworkoutassistant.shared.export.WorkoutDataExportRange
import com.google.accompanist.permissions.ExperimentalPermissionsApi
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.ZoneOffset

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
    onExportWorkoutDataForLlm: (WorkoutDataExportRange) -> Unit,
    onExportEquipment: () -> Unit,
    onClearAllExerciseInfo: () -> Unit,
    onViewErrorLogs: () -> Unit,
    onMenuItemClick: ((() -> Unit) -> Unit)? = null,
) {
    var showClearHistoryDialog by remember { mutableStateOf(false) }
    var showClearExerciseInfoDialog by remember { mutableStateOf(false) }
    var showWorkoutDataExportDialog by remember { mutableStateOf(false) }

    val scrollState = rememberScrollState()
    fun handleMenuItemClick(action: () -> Unit) {
        onMenuItemClick?.invoke(action) ?: action()
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(scrollState)
            .padding(vertical = 8.dp)
    ) {
        MenuSectionHeader("Settings", showDivider = false)
        WorkoutsMenuItem(
            label = "Settings",
            onClick = { handleMenuItemClick(onOpenSettingsClick) }
        )

        MenuSectionHeader("Sync")
        WorkoutsMenuItem(
            label = "Sync with Watch",
            onClick = { handleMenuItemClick(onSyncClick) }
        )
        WorkoutsMenuItem(
            label = "Sync with Health Connect",
            onClick = { handleMenuItemClick(onSyncWithHealthConnectClick) }
        )

        MenuSectionHeader("Export")
        WorkoutsMenuItem(
            label = "Export Workouts",
            onClick = { handleMenuItemClick(onExportWorkouts) }
        )
        WorkoutsMenuItem(
            label = "Export Workout Plan (Markdown)",
            onClick = { handleMenuItemClick(onExportWorkoutPlan) }
        )
        WorkoutsMenuItem(
            label = "Export Data for LLM (Markdown)",
            onClick = {
                handleMenuItemClick {
                    showWorkoutDataExportDialog = true
                }
            }
        )
        WorkoutsMenuItem(
            label = "Export Equipment (JSON)",
            onClick = { handleMenuItemClick(onExportEquipment) }
        )

        MenuSectionHeader("Data")
        WorkoutsMenuItem(
            label = "Save Backup",
            onClick = { handleMenuItemClick(onBackupClick) }
        )
        WorkoutsMenuItem(
            label = "Restore Backup",
            onClick = { handleMenuItemClick(onRestoreClick) }
        )
        WorkoutsMenuItem(
            label = "Import Workout Plan",
            onClick = { handleMenuItemClick(onImportWorkoutsClick) }
        )

        MenuSectionHeader("Maintenance")
        WorkoutsMenuItem(
            label = "Clear workout history",
            onClick = {
                handleMenuItemClick {
                    showClearHistoryDialog = true
                }
            }
        )
//        WorkoutsMenuItem(
//            label = "Clear all exercise info",
//            onClick = {
//                handleMenuItemClick {
//                    showClearExerciseInfoDialog = true
//                }
//            }
//        )

        MenuSectionHeader("Diagnostics")
        WorkoutsMenuItem(
            label = "View Error Logs",
            onClick = { handleMenuItemClick(onViewErrorLogs) }
        )
    }

    if (showWorkoutDataExportDialog) {
        WorkoutDataExportRangeDialog(
            onConfirm = { exportRange ->
                showWorkoutDataExportDialog = false
                onExportWorkoutDataForLlm(exportRange)
            },
            onDismiss = {
                showWorkoutDataExportDialog = false
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

private enum class WorkoutDataExportRangeSelection {
    ALL,
    CUSTOM,
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun WorkoutDataExportRangeDialog(
    onConfirm: (WorkoutDataExportRange) -> Unit,
    onDismiss: () -> Unit,
) {
    var selection by remember { mutableStateOf(WorkoutDataExportRangeSelection.ALL) }
    var showCustomRangePickerDialog by remember { mutableStateOf(false) }
    var selectedCustomStartMillis by remember { mutableStateOf<Long?>(null) }
    var selectedCustomEndMillis by remember { mutableStateOf<Long?>(null) }
    val today = remember { LocalDate.now() }
    val todayUtcMillis = remember(today) {
        today.atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli()
    }
    val selectableDates = remember(todayUtcMillis, today.year) {
        object : SelectableDates {
            override fun isSelectableDate(utcTimeMillis: Long): Boolean {
                return utcTimeMillis <= todayUtcMillis
            }

            override fun isSelectableYear(year: Int): Boolean {
                return year <= today.year
            }
        }
    }
    val hasCompleteCustomRange = selectedCustomStartMillis != null && selectedCustomEndMillis != null

    StandardDialog(
        onDismissRequest = onDismiss,
        title = "Export data for LLM",
        usePlatformDefaultWidth = false,
        body = {
            Column(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(5.dp)
            ) {
                WorkoutDataExportRangeOptionRow(
                    text = "All history",
                    selected = selection == WorkoutDataExportRangeSelection.ALL,
                    onClick = { selection = WorkoutDataExportRangeSelection.ALL }
                )
                WorkoutDataExportRangeOptionRow(
                    text = "Custom date range",
                    selected = selection == WorkoutDataExportRangeSelection.CUSTOM,
                    onClick = { selection = WorkoutDataExportRangeSelection.CUSTOM }
                )

                if (selection == WorkoutDataExportRangeSelection.CUSTOM) {
                    AppPrimaryOutlinedButton(
                        text = "Select date range",
                        onClick = { showCustomRangePickerDialog = true },
                        modifier = Modifier.fillMaxWidth(),
                        minHeight = 44.dp,
                    )
                    Text(
                        text = formatSelectedExportRange(selectedCustomStartMillis, selectedCustomEndMillis),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodyMedium,
                        modifier = Modifier.padding(horizontal = 2.dp)
                    )
                }
            }
        },
        confirmText = "Export",
        confirmEnabled = selection == WorkoutDataExportRangeSelection.ALL || hasCompleteCustomRange,
        onConfirm = {
            val exportRange = when (selection) {
                WorkoutDataExportRangeSelection.ALL -> WorkoutDataExportRange.ALL
                WorkoutDataExportRangeSelection.CUSTOM -> WorkoutDataExportRange.Custom(
                    customStartDate = requireNotNull(selectedCustomStartMillis).toLocalDate(),
                    customEndDate = requireNotNull(selectedCustomEndMillis).toLocalDate()
                )
            }
            onConfirm(exportRange)
        },
        dismissText = "Cancel",
        onDismissButton = onDismiss
    )

    if (showCustomRangePickerDialog) {
        val dateRangePickerState = rememberDateRangePickerState(
            initialSelectedStartDateMillis = selectedCustomStartMillis,
            initialSelectedEndDateMillis = selectedCustomEndMillis,
            selectableDates = selectableDates
        )
        DatePickerDialog(
            onDismissRequest = { showCustomRangePickerDialog = false },
            confirmButton = {
                DialogOutlinedButton(
                    text = "OK",
                    onClick = {
                        selectedCustomStartMillis = dateRangePickerState.selectedStartDateMillis
                        selectedCustomEndMillis = dateRangePickerState.selectedEndDateMillis
                        showCustomRangePickerDialog = false
                    }
                )
            },
            dismissButton = {
                DialogOutlinedButton(
                    text = "Cancel",
                    onClick = { showCustomRangePickerDialog = false }
                )
            }
        ) {
            DateRangePicker(
                state = dateRangePickerState,
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(max = 560.dp),
                title = null,
                headline = null,
                showModeToggle = false
            )
        }
    }
}

@Composable
private fun WorkoutDataExportRangeOptionRow(
    text: String,
    selected: Boolean,
    onClick: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        horizontalArrangement = Arrangement.spacedBy(5.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        RadioButton(
            selected = selected,
            onClick = onClick
        )
        Text(
            text = text,
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.bodyMedium
        )
    }
}

private fun formatSelectedExportRange(
    selectedStartMillis: Long?,
    selectedEndMillis: Long?,
): String {
    val startDate = selectedStartMillis?.toLocalDate()
    val endDate = selectedEndMillis?.toLocalDate()
    return when {
        startDate != null && endDate != null -> "Selected: $startDate to $endDate"
        startDate != null -> "Selected start: $startDate"
        else -> "Select a start and end date."
    }
}

private fun Long.toLocalDate(): LocalDate {
    return Instant.ofEpochMilli(this)
        .atZone(ZoneId.systemDefault())
        .toLocalDate()
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
