package com.gabstra.myworkoutassistant.composables

import androidx.activity.compose.BackHandler
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
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Build
import androidx.compose.material.icons.filled.Link
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Storage
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
                WorkoutsMenuPage.HOME -> "Menu"
                WorkoutsMenuPage.CONNECTIONS -> "Connections"
                WorkoutsMenuPage.DATA -> "Data"
                WorkoutsMenuPage.ADVANCED -> "Advanced"
            },
            showBack = currentPage != WorkoutsMenuPage.HOME,
            onBack = { currentPage = WorkoutsMenuPage.HOME },
        )

        when (currentPage) {
            WorkoutsMenuPage.HOME -> {
                MenuDestinationCard(
                    icon = Icons.Default.Settings,
                    title = "Settings",
                    subtitle = "App preferences",
                    onClick = { handleMenuItemClick(onOpenSettingsClick) },
                )
                MenuDestinationCard(
                    icon = Icons.Default.Link,
                    title = "Connections",
                    subtitle = "Watch and Health Connect",
                    onClick = { currentPage = WorkoutsMenuPage.CONNECTIONS },
                )
                MenuDestinationCard(
                    icon = Icons.Default.Storage,
                    title = "Data",
                    subtitle = "Backup, restore and imports",
                    onClick = { currentPage = WorkoutsMenuPage.DATA },
                )
                MenuDestinationCard(
                    icon = Icons.Default.Build,
                    title = "Advanced",
                    subtitle = "Exports and diagnostics",
                    onClick = { currentPage = WorkoutsMenuPage.ADVANCED },
                )
            }

            WorkoutsMenuPage.CONNECTIONS -> MenuActionGroup(
                actions = listOf(
                    "Sync with watch" to { handleMenuItemClick(onSyncClick) },
                    "Sync with Health Connect" to { handleMenuItemClick(onSyncWithHealthConnectClick) },
                )
            )

            WorkoutsMenuPage.DATA -> {
                StyledCard(
                    modifier = Modifier.fillMaxWidth(),
                    backgroundColor = MaterialTheme.colorScheme.surfaceContainerLow,
                ) {
                    Column {
                        MinimalMenuAction(
                            label = "Save backup",
                            onClick = { handleMenuItemClick(onBackupClick) },
                        )
                        MinimalMenuDivider()
                        MinimalMenuAction(
                            label = "Restore backup",
                            onClick = { handleMenuItemClick(onRestoreClick) },
                        )
                        MinimalMenuDivider()
                        MinimalMenuAction(
                            label = "Import workout plan",
                            onClick = { handleMenuItemClick(onImportWorkoutsClick) },
                        )
                        MinimalMenuDivider()
                        MinimalMenuAction(
                            label = "Clear workout history",
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
                    "Export workouts" to { handleMenuItemClick(onExportWorkouts) },
                    "Export workout plan" to { handleMenuItemClick(onExportWorkoutPlan) },
                    "Export data for AI" to {
                        handleMenuItemClick { showWorkoutDataExportDialog = true }
                    },
                    "Export equipment" to { handleMenuItemClick(onExportEquipment) },
                    "View error logs" to { handleMenuItemClick(onViewErrorLogs) },
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
                DialogDismissButton(
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
                contentDescription = "Back to menu",
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
    onClick: () -> Unit,
) {
    StyledCard(
        modifier = Modifier
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
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
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
