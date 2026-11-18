package com.gabstra.myworkoutassistant.composables

import androidx.activity.compose.BackHandler
import com.gabstra.myworkoutassistant.ui.theme.tertiaryContent
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.DateRangePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.RadioButton
import androidx.compose.material3.SelectableDates
import androidx.compose.material3.Text
import androidx.compose.material3.rememberDateRangePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Build
import androidx.compose.material.icons.filled.Link
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Storage
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.shared.export.WorkoutDataExportRange
import com.google.accompanist.permissions.ExperimentalPermissionsApi
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.ZoneOffset

private enum class WorkoutsMenuPage {
    HOME,
    CONNECTIONS,
    DATA,
    ADVANCED,
}

@OptIn(ExperimentalPermissionsApi::class)
@Composable
fun WorkoutsMenu(
    isDrawerOpen: Boolean,
    onSyncClick: () -> Unit,
    onBackupClick: () -> Unit,
    onRestoreClick: () -> Unit,
    onImportWorkoutsClick: () -> Unit,
    onOpenSettingsClick: () -> Unit,
    onOpenPlansClick: () -> Unit,
    onClearAllHistories: () -> Unit,
    onSyncWithHealthConnectClick: () -> Unit,
    onExportWorkouts: () -> Unit,
    onExportWorkoutPlan: () -> Unit,
    onExportWorkoutDataForLlm: (WorkoutDataExportRange) -> Unit,
    onExportEquipment: () -> Unit,
    onClearAllExerciseInfo: () -> Unit,
    onViewErrorLogs: () -> Unit,
    onViewSensorSessions: () -> Unit,
    onMenuItemClick: ((() -> Unit) -> Unit)? = null,
) {
    var showClearHistoryDialog by remember { mutableStateOf(false) }
    var showClearExerciseInfoDialog by remember { mutableStateOf(false) }
    var showWorkoutDataExportDialog by remember { mutableStateOf(false) }
    var currentPage by remember { mutableStateOf(WorkoutsMenuPage.HOME) }

    val scrollState = rememberScrollState()
    fun handleMenuItemClick(action: () -> Unit) {
        currentPage = WorkoutsMenuPage.HOME
        onMenuItemClick?.invoke(action) ?: action()
    }

    BackHandler(enabled = currentPage != WorkoutsMenuPage.HOME) {
        currentPage = WorkoutsMenuPage.HOME
    }
    LaunchedEffect(isDrawerOpen) {
        if (!isDrawerOpen) currentPage = WorkoutsMenuPage.HOME
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(scrollState)
            .padding(horizontal = 16.dp, vertical = 12.dp)
    ) {
        MinimalMenuHeader(
            title = when (currentPage) {
                WorkoutsMenuPage.HOME -> stringResource(R.string.loc_menu)
                WorkoutsMenuPage.CONNECTIONS -> stringResource(R.string.loc_connections)
                WorkoutsMenuPage.DATA -> stringResource(R.string.loc_data)
                WorkoutsMenuPage.ADVANCED -> stringResource(R.string.loc_advanced)
            },
            showBack = currentPage != WorkoutsMenuPage.HOME,
            onBack = { currentPage = WorkoutsMenuPage.HOME },
        )

        when (currentPage) {
            WorkoutsMenuPage.HOME -> {
                MenuDestinationCard(
                    icon = Icons.Default.Settings,
                    title = stringResource(R.string.loc_settings_cd),
                    subtitle = stringResource(R.string.loc_app_preferences),
                    onClick = { handleMenuItemClick(onOpenSettingsClick) },
                )
                MenuDestinationCard(
                    icon = Icons.Default.Storage,
                    title = stringResource(R.string.loc_plans),
                    subtitle = stringResource(R.string.loc_edit_workout_plan_settings),
                    modifier = Modifier.testTag("navigation_plans"),
                    onClick = { handleMenuItemClick(onOpenPlansClick) },
                )
                MenuDestinationCard(
                    icon = Icons.Default.Link,
                    title = stringResource(R.string.loc_connections),
                    subtitle = stringResource(R.string.loc_watch_and_health_connect),
                    onClick = { currentPage = WorkoutsMenuPage.CONNECTIONS },
                )
                MenuDestinationCard(
                    icon = Icons.Default.Storage,
                    title = stringResource(R.string.loc_data),
                    subtitle = stringResource(R.string.loc_backup_restore_imports),
                    onClick = { currentPage = WorkoutsMenuPage.DATA },
                )
                MenuDestinationCard(
                    icon = Icons.Default.Build,
                    title = stringResource(R.string.loc_advanced),
                    subtitle = stringResource(R.string.loc_exports_and_diagnostics),
                    onClick = { currentPage = WorkoutsMenuPage.ADVANCED },
                )
            }

            WorkoutsMenuPage.CONNECTIONS -> MenuActionGroup(
                actions = listOf(
                    stringResource(R.string.loc_sync_with_watch) to {
                        handleMenuItemClick(onSyncClick)
                    },
                    stringResource(R.string.loc_sync_with_health_connect) to {
                        handleMenuItemClick(onSyncWithHealthConnectClick)
                    },
                )
            )

            WorkoutsMenuPage.DATA -> {
                StyledCard(
                    modifier = Modifier.fillMaxWidth(),
                    backgroundColor = MaterialTheme.colorScheme.surfaceContainerLow,
                ) {
                    Column {
                        MinimalMenuAction(
                            label = stringResource(R.string.main_save_backup_title),
                            onClick = { handleMenuItemClick(onBackupClick) },
                        )
                        MinimalMenuDivider()
                        MinimalMenuAction(
                            label = stringResource(R.string.loc_restore_backup),
                            onClick = { handleMenuItemClick(onRestoreClick) },
                        )
                        MinimalMenuDivider()
                        MinimalMenuAction(
                            label = stringResource(R.string.loc_import_plan_or_history),
                            onClick = { handleMenuItemClick(onImportWorkoutsClick) },
                        )
                        MinimalMenuDivider()
                        MinimalMenuAction(
                            label = stringResource(R.string.loc_clear_workout_history),
                            isDestructive = true,
                            onClick = {
                                handleMenuItemClick { showClearHistoryDialog = true }
                            },
                        )
                    }
                }
            }

            WorkoutsMenuPage.ADVANCED -> MenuActionGroup(
                actions = listOf(
                    stringResource(R.string.loc_sensor_sessions) to {
                        handleMenuItemClick(onViewSensorSessions)
                    },
                    stringResource(R.string.loc_export_workouts) to {
                        handleMenuItemClick(onExportWorkouts)
                    },
                    stringResource(R.string.loc_export_workout_plan) to {
                        handleMenuItemClick(onExportWorkoutPlan)
                    },
                    stringResource(R.string.loc_export_data_for_ai) to {
                        handleMenuItemClick { showWorkoutDataExportDialog = true }
                    },
                    stringResource(R.string.loc_export_equipment) to {
                        handleMenuItemClick(onExportEquipment)
                    },
                    stringResource(R.string.loc_view_error_logs) to {
                        handleMenuItemClick(onViewErrorLogs)
                    },
                )
            )
        }
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
        title = stringResource(R.string.loc_clear_workout_history_title),
        message = stringResource(R.string.loc_clear_workout_history_message),
        confirmText = stringResource(R.string.loc_clear),
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
        title = stringResource(R.string.loc_clear_exercise_info_title),
        message = stringResource(R.string.loc_clear_exercise_info_message),
        confirmText = stringResource(R.string.loc_clear),
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
        title = stringResource(R.string.loc_export_data_for_llm_title),
        usePlatformDefaultWidth = false,
        body = {
            Column(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(5.dp)
            ) {
                WorkoutDataExportRangeOptionRow(
                    text = stringResource(R.string.loc_all_history),
                    selected = selection == WorkoutDataExportRangeSelection.ALL,
                    onClick = { selection = WorkoutDataExportRangeSelection.ALL }
                )
                WorkoutDataExportRangeOptionRow(
                    text = stringResource(R.string.loc_custom_date_range),
                    selected = selection == WorkoutDataExportRangeSelection.CUSTOM,
                    onClick = { selection = WorkoutDataExportRangeSelection.CUSTOM }
                )

                if (selection == WorkoutDataExportRangeSelection.CUSTOM) {
                    AppPrimaryOutlinedButton(
                        text = stringResource(R.string.loc_select_date_range),
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
        confirmText = stringResource(R.string.loc_export),
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
        dismissText = stringResource(R.string.common_cancel),
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
                    text = stringResource(R.string.workout_ok),
                    onClick = {
                        selectedCustomStartMillis = dateRangePickerState.selectedStartDateMillis
                        selectedCustomEndMillis = dateRangePickerState.selectedEndDateMillis
                        showCustomRangePickerDialog = false
                    }
                )
            },
            dismissButton = {
                DialogDismissButton(
                    text = stringResource(R.string.common_cancel),
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

@Composable
private fun formatSelectedExportRange(
    selectedStartMillis: Long?,
    selectedEndMillis: Long?,
): String {
    val startDate = selectedStartMillis?.toLocalDate()
    val endDate = selectedEndMillis?.toLocalDate()
    return when {
        startDate != null && endDate != null ->
            stringResource(R.string.loc_selected_range, startDate.toString(), endDate.toString())
        startDate != null -> stringResource(R.string.loc_selected_start, startDate.toString())
        else -> stringResource(R.string.loc_select_start_end_date)
    }
}

private fun Long.toLocalDate(): LocalDate {
    return Instant.ofEpochMilli(this)
        .atZone(ZoneId.systemDefault())
        .toLocalDate()
}

@Composable
private fun MinimalMenuHeader(
    title: String,
    showBack: Boolean,
    onBack: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(bottom = 20.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (showBack) {
            Icon(
                imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                contentDescription = stringResource(R.string.loc_back_to_menu_cd),
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier
                    .size(40.dp)
                    .clickable(onClick = onBack)
                    .padding(8.dp),
            )
        }
        Text(
            text = title,
            style = MaterialTheme.typography.titleLarge,
            color = MaterialTheme.colorScheme.onSurface,
            fontWeight = FontWeight.Medium,
            modifier = if (showBack) Modifier.padding(start = 4.dp) else Modifier,
        )
    }
}

@Composable
private fun MenuDestinationCard(
    icon: ImageVector,
    title: String,
    subtitle: String,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    StyledCard(
        modifier = modifier
            .fillMaxWidth()
            .padding(bottom = 10.dp)
            .clickable(onClick = onClick),
        backgroundColor = MaterialTheme.colorScheme.surfaceContainerLow,
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 14.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.size(22.dp),
            )
            Column(
                modifier = Modifier
                    .weight(1f)
                    .padding(horizontal = 14.dp),
                verticalArrangement = Arrangement.spacedBy(2.dp),
            ) {
                Text(
                    text = title,
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurface,
                    fontWeight = FontWeight.Medium,
                )
                Text(
                    text = subtitle,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.tertiaryContent,
                )
            }
            Icon(
                imageVector = Icons.AutoMirrored.Filled.KeyboardArrowRight,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.size(20.dp),
            )
        }
    }
}

@Composable
private fun MenuActionGroup(actions: List<Pair<String, () -> Unit>>) {
    StyledCard(
        modifier = Modifier.fillMaxWidth(),
        backgroundColor = MaterialTheme.colorScheme.surfaceContainerLow,
    ) {
        Column {
            actions.forEachIndexed { index, (label, onClick) ->
                MinimalMenuAction(label = label, onClick = onClick)
                if (index < actions.lastIndex) {
                    MinimalMenuDivider()
                }
            }
        }
    }
}

@Composable
private fun MinimalMenuDivider() {
    HorizontalDivider(
        modifier = Modifier.padding(horizontal = 16.dp),
        color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f),
    )
}

@Composable
private fun MinimalMenuAction(
    label: String,
    isDestructive: Boolean = false,
    onClick: () -> Unit,
) {
    Text(
        text = label,
        style = MaterialTheme.typography.bodyLarge,
        color = if (isDestructive) {
            MaterialTheme.colorScheme.error
        } else {
            MaterialTheme.colorScheme.onSurface
        },
        fontWeight = FontWeight.Normal,
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 15.dp),
    )
}
