package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.TabRowDefaults
import androidx.compose.material3.TabRowDefaults.tabIndicatorOffset
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TimePicker
import androidx.compose.material3.TimePickerState
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.material3.rememberTimePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.foundation.interaction.Interaction
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.health.connect.client.records.ExerciseSessionRecord
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.AppMenuContent
import com.gabstra.myworkoutassistant.composables.AppDropdownMenuItem
import com.gabstra.myworkoutassistant.composables.CustomButton
import com.gabstra.myworkoutassistant.composables.DialogTextButton
import com.gabstra.myworkoutassistant.composables.StandardDialog
import com.gabstra.myworkoutassistant.WorkoutTypes
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutSchedule
import com.gabstra.myworkoutassistant.shared.utils.ScheduleConflictChecker
import com.gabstra.myworkoutassistant.verticalColumnScrollbar
import android.widget.Toast
import androidx.compose.ui.platform.LocalContext
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.util.Locale
import java.util.UUID
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WorkoutForm(
    onWorkoutUpsert: (Workout, List<WorkoutSchedule>) -> Unit,
    onCancel: () -> Unit,
    workout: Workout? = null,
    isSaving: Boolean = false,
    existingSchedules: List<WorkoutSchedule> = emptyList()
) {
    // ---- state ----
    val workoutNameState = rememberSaveable { mutableStateOf(workout?.name ?: "") }
    val workoutDescriptionState = rememberSaveable { mutableStateOf(workout?.description ?: "") }
    val timesCompletedInAWeekState = rememberSaveable { mutableStateOf(workout?.timesCompletedInAWeek?.toString() ?: "0") }
    val usePolarDeviceState = rememberSaveable { mutableStateOf(workout?.usePolarDevice ?: false) }

    val selectedWorkoutType = rememberSaveable { mutableStateOf(workout?.type ?: ExerciseSessionRecord.EXERCISE_TYPE_STRENGTH_TRAINING) }
    var workoutTypeExpanded by rememberSaveable { mutableStateOf(false) }

    val schedules = remember(existingSchedules) { mutableStateOf(existingSchedules.toMutableList()) }
    val showScheduleDialog = remember { mutableStateOf(false) }
    val currentEditingSchedule = remember { mutableStateOf<WorkoutSchedule?>(null) }

    val showBatchScheduleDialog = remember { mutableStateOf(false) }

    val newGlobalId = remember { workout?.globalId ?: UUID.randomUUID() }

    val scrollState = rememberScrollState()
    val outlineVariant = MaterialTheme.colorScheme.outlineVariant
    val dropdownBackground = MaterialTheme.colorScheme.surfaceVariant
    val dropdownBorderColor = MaterialTheme.colorScheme.outlineVariant

    Box(modifier = Modifier.fillMaxSize()) {
        Scaffold(
            topBar = {
                TopAppBar(
                    modifier = Modifier.drawBehind {
                        drawLine(
                            color = outlineVariant,
                            start = Offset(0f, size.height),
                            end = Offset(size.width, size.height),
                            strokeWidth = 1.dp.toPx()
                        )
                    },
                    title = {
                        Text(
                            modifier = Modifier
                                .fillMaxWidth()
                                .basicMarquee(iterations = Int.MAX_VALUE),
                            text = if (workout == null) "Insert Workout" else "Edit Workout",
                            textAlign = TextAlign.Center,
                            style = MaterialTheme.typography.titleLarge
                        )
                    },
                    colors = TopAppBarDefaults.topAppBarColors(
                        containerColor = Color.Transparent,
                        navigationIconContentColor = MaterialTheme.colorScheme.onBackground,
                        actionIconContentColor = MaterialTheme.colorScheme.onBackground
                    ),
                    navigationIcon = {
                        IconButton(onClick = onCancel, enabled = !isSaving) {
                            Icon(
                                imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                                contentDescription = "Back"
                            )
                        }
                    },
                    actions = {
                        // invisible icon to keep title centered like in ExerciseForm
                        IconButton(modifier = Modifier.alpha(0f), onClick = { }) {
                            Icon(
                                imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                                contentDescription = "Back"
                            )
                        }
                    }
                )
            }
        ) { padding ->
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding)
                    .padding(top = 10.dp)
                    .padding(bottom = 10.dp)
                    .verticalColumnScrollbar(scrollState)
                    .verticalScroll(scrollState)
                    .padding(horizontal = 15.dp),
            ) {
                // Name
                OutlinedTextField(
                    value = workoutNameState.value,
                    onValueChange = { workoutNameState.value = it },
                    label = { Text("Workout name", style = MaterialTheme.typography.labelLarge) },
                    modifier = Modifier.fillMaxWidth()
                )

            Spacer(Modifier.height(Spacing.lg))

            // Description
            OutlinedTextField(
                value = workoutDescriptionState.value,
                onValueChange = { workoutDescriptionState.value = it },
                label = { Text("Description", style = MaterialTheme.typography.labelLarge) },
                modifier = Modifier.fillMaxWidth(),
                maxLines = 5,
                singleLine = false
            )

            Spacer(Modifier.height(Spacing.lg))

            ExposedDropdownMenuBox(
                expanded = workoutTypeExpanded,
                onExpandedChange = { workoutTypeExpanded = it }
            ) {
                val typeLabel = remember(selectedWorkoutType.value) {
                    WorkoutTypes.GetNameFromInt(selectedWorkoutType.value)
                    .replace('_', ' ')
                    .lowercase(Locale.ROOT)
                    .replaceFirstChar { if (it.isLowerCase()) it.titlecase(Locale.ROOT) else it.toString() }
                }

                OutlinedTextField(
                    value = typeLabel,
                    label = { Text("Workout type", style = MaterialTheme.typography.labelLarge) },
                    onValueChange = {},
                    readOnly = true,
                    trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(workoutTypeExpanded) },
                    modifier = Modifier
                        .fillMaxWidth()
                        .menuAnchor()
                )

                ExposedDropdownMenu(
                    expanded = workoutTypeExpanded,
                    modifier = Modifier.background(dropdownBackground),
                    border = BorderStroke(1.dp, dropdownBorderColor),
                    onDismissRequest = { workoutTypeExpanded = false }
                ) {
                    AppMenuContent {
                        WorkoutTypes.WORKOUT_TYPE_STRING_TO_INT_MAP.keys.forEach { key ->
                            AppDropdownMenuItem(
                                text = {
                                    Text(
                                        key.replace('_', ' ').lowercase(Locale.ROOT)
                                            .replaceFirstChar { if (it.isLowerCase()) it.titlecase(Locale.ROOT) else it.toString() }
                                    )
                                },
                                onClick = {
                                    selectedWorkoutType.value = WorkoutTypes.WORKOUT_TYPE_STRING_TO_INT_MAP[key]!!
                                    workoutTypeExpanded = false
                                }
                            )
                        }
                    }
                }
            }

            // Target sessions per week
            Spacer(Modifier.height(Spacing.lg))

            OutlinedTextField(
                value = timesCompletedInAWeekState.value,
                onValueChange = { input ->
                    if (input.isEmpty() || input.all { it.isDigit() }) {
                        timesCompletedInAWeekState.value = input
                    }
                },
                label = { Text("Target sessions per week", style = MaterialTheme.typography.labelLarge) },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.fillMaxWidth()
            )

            // Use Polar toggle (aligned style)
            ListItem(
                colors = ListItemDefaults.colors().copy(containerColor = Color.Transparent),
                headlineContent = { Text("Use Polar device", style = MaterialTheme.typography.bodyLarge) },
                trailingContent = {
                    Switch(
                        checked = usePolarDeviceState.value,
                        onCheckedChange = { usePolarDeviceState.value = it }
                    )
                }
            )
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

            // ---- Schedules --------------------------------------------------
            Spacer(Modifier.height(Spacing.lg))
            Text(
                text = "Workout schedule",
                style = MaterialTheme.typography.titleMedium,
            )

            Spacer(Modifier.height(Spacing.md))

            if (schedules.value.isEmpty()) {
                Text(
                    text = "No schedules set",
                    style = MaterialTheme.typography.bodyMedium
                )
            } else {
                Column(verticalArrangement = Arrangement.spacedBy(Spacing.sm)) {
                    schedules.value.forEachIndexed { index, schedule ->
                        ScheduleListItem(
                            schedule = schedule,
                            index = index,
                            onEdit = {
                                currentEditingSchedule.value = schedule
                                showScheduleDialog.value = true
                            },
                            onDelete = {
                                val updated = schedules.value.toMutableList()
                                updated.removeAt(index)
                                schedules.value = updated
                            }
                        )
                    }
                }
            }

            Spacer(Modifier.height(Spacing.md))

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(Spacing.md)
            ) {
                Button(
                    onClick = {
                        currentEditingSchedule.value = null
                        showScheduleDialog.value = true
                    },
                    modifier = Modifier.weight(1f)
                ) { Text("Add Single", color = MaterialTheme.colorScheme.onPrimary) }

                Button(
                    onClick = { showBatchScheduleDialog.value = true },
                    modifier = Modifier.weight(1f)
                ) { Text("Add Multiple", color = MaterialTheme.colorScheme.onPrimary) }
            }

            Spacer(Modifier.height(Spacing.md))
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

            Spacer(Modifier.height(Spacing.xl))

            // ---- Actions ----------------------------------------------------
            val canBeSaved = workoutNameState.value.isNotBlank()

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(Spacing.md),
                verticalAlignment = Alignment.CenterVertically
            ) {
                    CustomButton(
                        text = "Cancel",
                        onClick = onCancel,
                        enabled = !isSaving,
                        modifier = Modifier.weight(1f)
                    )

                    Button(
                        onClick = {
                            val newWorkout = Workout(
                                id = workout?.id ?: UUID.randomUUID(),
                                name = workoutNameState.value.trim(),
                                description = workoutDescriptionState.value.trim(),
                                workoutComponents = workout?.workoutComponents ?: listOf(),
                                usePolarDevice = usePolarDeviceState.value,
                                creationDate = LocalDate.now(),
                                order = workout?.order ?: 0,
                                timesCompletedInAWeek = timesCompletedInAWeekState.value.toIntOrNull(),
                                globalId = newGlobalId,
                                type = selectedWorkoutType.value
                            )
                            onWorkoutUpsert(newWorkout, schedules.value)
                        },
                        enabled = canBeSaved && !isSaving,
                        modifier = Modifier.weight(1f)
                    ) { Text(if (workout == null) "Insert" else "Save", style = MaterialTheme.typography.bodyLarge) }
                }

            Spacer(Modifier.height(Spacing.xl))
            }
        }
        if (isSaving) {
            val interactionSource = remember { MutableInteractionSource() }
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(MaterialTheme.colorScheme.surface.copy(alpha = 0.75f))
                    .clickable(
                        interactionSource = interactionSource,
                        indication = null,
                        onClick = {}
                    ),
                contentAlignment = Alignment.Center
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    CircularProgressIndicator()
                    Spacer(Modifier.height(Spacing.md))
                    Text(text = "Saving...", style = MaterialTheme.typography.bodyLarge)
                }
            }
        }
    }

    // ---- Dialogs -----------------------------------------------------------
    if (showScheduleDialog.value) {
        ScheduleDialog(
            schedule = currentEditingSchedule.value,
            workoutId = newGlobalId,
            existingSchedules = schedules.value,
            onDismiss = { showScheduleDialog.value = false },
            onSave = { newSchedule ->
                val updated = schedules.value.toMutableList()
                val idx = updated.indexOfFirst { it.id == newSchedule.id }
                if (idx >= 0) updated[idx] = newSchedule else updated.add(newSchedule)
                schedules.value = updated
                showScheduleDialog.value = false
            }
        )
    }

    if (showBatchScheduleDialog.value) {
        BatchScheduleDialog(
            workoutId = newGlobalId,
            existingSchedules = schedules.value,
            onDismiss = { showBatchScheduleDialog.value = false },
            onSave = { newSchedules ->
                val updated = schedules.value.toMutableList()
                updated.addAll(newSchedules)
                schedules.value = updated
                showBatchScheduleDialog.value = false
            }
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ScheduleDialog(
    schedule: WorkoutSchedule?,
    workoutId: UUID,
    existingSchedules: List<WorkoutSchedule>,
    onDismiss: () -> Unit,
    onSave: (WorkoutSchedule) -> Unit
) {
    val context = LocalContext.current
    val isEditing = schedule != null

    val labelState = rememberSaveable { mutableStateOf(schedule?.label ?: "") }
    val hourState = rememberSaveable { mutableIntStateOf(schedule?.hour ?: 8) }
    val minuteState = rememberSaveable { mutableIntStateOf(schedule?.minute ?: 0) }
    val isEnabledState = rememberSaveable { mutableStateOf(schedule?.isEnabled ?: true) }

    val useSpecificDate = rememberSaveable { mutableStateOf(schedule?.specificDate != null) }

    val daysOfWeekState = rememberSaveable { mutableIntStateOf(schedule?.daysOfWeek ?: 0) }

    val datePickerState = rememberDatePickerState(
        initialSelectedDateMillis = schedule?.specificDate?.atStartOfDay(ZoneId.systemDefault())?.toInstant()?.toEpochMilli()
            ?: System.currentTimeMillis()
    )
    val showDatePicker = remember { mutableStateOf(false) }

    val timePickerState = rememberTimePickerState(
        initialHour = hourState.intValue,
        initialMinute = minuteState.intValue
    )
    val showTimePicker = remember { mutableStateOf(false) }

    StandardDialog(
        onDismissRequest = onDismiss,
        title = if (isEditing) "Edit schedule" else "Add schedule",
        body = {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(Spacing.sm)
            ) {
                OutlinedTextField(
                    value = labelState.value,
                    onValueChange = { labelState.value = it },
                    label = { Text("Label (optional)", style = MaterialTheme.typography.labelLarge) },
                    modifier = Modifier.fillMaxWidth()
                )

                Spacer(Modifier.height(Spacing.lg))

                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("Time", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.width(Spacing.md))
                    Button(onClick = { showTimePicker.value = true }) {
                        Text("${hourState.intValue}:${minuteState.intValue.toString().padStart(2, '0')}")
                    }
                }

                Spacer(Modifier.height(Spacing.lg))
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)


                ListItem(
                    colors = ListItemDefaults.colors().copy(containerColor = Color.Transparent),
                    headlineContent = { Text("Use specific date", style = MaterialTheme.typography.bodyLarge) },
                    trailingContent = {
                        Switch(
                            checked = useSpecificDate.value,
                            onCheckedChange = { useSpecificDate.value = it }
                        )
                    }
                )
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

                Spacer(Modifier.height(Spacing.lg))

                if (useSpecificDate.value) {
                    val date = datePickerState.selectedDateMillis?.let {
                        Instant.ofEpochMilli(it).atZone(ZoneId.systemDefault()).toLocalDate()
                    } ?: LocalDate.now()

                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("Date", style = MaterialTheme.typography.titleMedium)
                        Spacer(Modifier.width(Spacing.md))
                        Button(onClick = { showDatePicker.value = true }) { Text(date.toString()) }
                    }
                } else {
                    Text("Days of week", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(Spacing.sm))
                    WeekdaySelectionRow(
                        days = listOf("Mon", "Tue", "Wed", "Thu"),
                        bitValues = listOf(2, 4, 8, 16),
                        daysOfWeekState = daysOfWeekState
                    )
                    WeekdaySelectionRow(
                        days = listOf("Fri", "Sat", "Sun", ""),
                        bitValues = listOf(32, 64, 1, 0),
                        daysOfWeekState = daysOfWeekState,
                        showLastCheckbox = false
                    )
                }

                Spacer(Modifier.height(Spacing.lg))
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)


                ListItem(
                    colors = ListItemDefaults.colors().copy(containerColor = Color.Transparent),
                    headlineContent = { Text("Enabled", style = MaterialTheme.typography.bodyLarge) },
                    trailingContent = {
                        Switch(
                            checked = isEnabledState.value,
                            onCheckedChange = { isEnabledState.value = it }
                        )
                    }
                )
            }
        },
        confirmText = "Save",
        onConfirm = {
            val specificDate = if (useSpecificDate.value) {
                datePickerState.selectedDateMillis?.let {
                    Instant.ofEpochMilli(it).atZone(ZoneId.systemDefault()).toLocalDate()
                }
            } else null

            val newSchedule = WorkoutSchedule(
                id = schedule?.id ?: UUID.randomUUID(),
                workoutId = workoutId,
                label = labelState.value,
                hour = hourState.intValue,
                minute = minuteState.intValue,
                isEnabled = isEnabledState.value,
                daysOfWeek = if (useSpecificDate.value) 0 else daysOfWeekState.intValue,
                specificDate = specificDate,
                hasExecuted = schedule?.hasExecuted ?: false
            )

            // Check for conflicts
            val conflicts = ScheduleConflictChecker.checkScheduleConflicts(
                newSchedules = listOf(newSchedule),
                existingSchedules = existingSchedules.filter { it.id != newSchedule.id }
            )

            if (conflicts.isNotEmpty()) {
                val errorMessage = ScheduleConflictChecker.formatConflictMessage(conflicts)
                Toast.makeText(context, errorMessage, Toast.LENGTH_LONG).show()
            } else {
                onSave(newSchedule)
            }
        },
        dismissText = "Cancel",
        onDismissButton = onDismiss
    )

    if (showTimePicker.value) {
        TimePickerDialog(
            onDismiss = { showTimePicker.value = false },
            onConfirm = {
                hourState.intValue = timePickerState.hour
                minuteState.intValue = timePickerState.minute
                showTimePicker.value = false
            },
            timePickerState = timePickerState
        )
    }

    if (showDatePicker.value) {
        DatePickerDialog(
            onDismissRequest = { showDatePicker.value = false },
            confirmButton = {
                DialogTextButton(
                    text = "OK",
                    onClick = { showDatePicker.value = false }
                )
            },
            dismissButton = {
                DialogTextButton(
                    text = "Cancel",
                    onClick = { showDatePicker.value = false }
                )
            }
        ) { DatePicker(state = datePickerState) }
    }
}

@Composable
fun WeekdaySelectionRow(
    days: List<String>,
    bitValues: List<Int>,
    daysOfWeekState: androidx.compose.runtime.MutableIntState,
    showLastCheckbox: Boolean = true
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        days.forEachIndexed { index, day ->
            if (index == days.lastIndex && !showLastCheckbox) {
                Box(modifier = Modifier.width(48.dp))
            } else if (day.isNotEmpty()) {
                DayOfWeekCheckbox(
                    day = day,
                    isChecked = (daysOfWeekState.intValue and bitValues[index]) != 0,
                    onCheckedChange = { checked ->
                        daysOfWeekState.intValue = if (checked) {
                            daysOfWeekState.intValue or bitValues[index]
                        } else {
                            daysOfWeekState.intValue and bitValues[index].inv()
                        }
                    }
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TimePickerDialog(
    onDismiss: () -> Unit,
    onConfirm: () -> Unit,
    timePickerState: TimePickerState
) {
    StandardDialog(
        onDismissRequest = onDismiss,
        title = "Select time",
        body = { TimePicker(state = timePickerState) },
        confirmText = "OK",
        onConfirm = onConfirm,
        dismissText = "Cancel",
        onDismissButton = onDismiss
    )
}

@Composable
fun DayOfWeekCheckbox(
    day: String,
    isChecked: Boolean,
    onCheckedChange: (Boolean) -> Unit
) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(text = day, style = MaterialTheme.typography.bodySmall)
        androidx.compose.material3.Checkbox(
            checked = isChecked,
            onCheckedChange = onCheckedChange
        )
    }
}

fun getDaysOfWeekString(daysOfWeek: Int): String {
    val dayPairs = listOf(
        1 to "Sun", 2 to "Mon", 4 to "Tue", 8 to "Wed",
        16 to "Thu", 32 to "Fri", 64 to "Sat"
    )
    val days = dayPairs.filter { (bit, _) -> (daysOfWeek and bit) != 0 }.map { it.second }
    return when {
        days.isEmpty() -> "No days selected"
        days.size == 7 -> "Every day"
        days.size == 5 && !days.contains("Sat") && !days.contains("Sun") -> "Weekdays"
        days.size == 2 && days.contains("Sat") && days.contains("Sun") -> "Weekends"
        else -> days.joinToString(", ")
    }
}

@Composable
fun ScheduleListItem(
    schedule: WorkoutSchedule,
    index: Int,
    onEdit: () -> Unit,
    onDelete: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = Spacing.sm),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(Spacing.md)
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = if (schedule.label.isNotEmpty()) schedule.label else "Schedule ${index + 1}",
                style = MaterialTheme.typography.bodyMedium
            )
            Text(
                text = if (schedule.specificDate != null) {
                    "On ${schedule.specificDate} at ${schedule.hour}:${schedule.minute.toString().padStart(2, '0')}"
                } else {
                    val days = getDaysOfWeekString(schedule.daysOfWeek)
                    "Every $days at ${schedule.hour}:${schedule.minute.toString().padStart(2, '0')}"
                },
                style = MaterialTheme.typography.bodySmall
            )
        }
        Text(text = "Edit", modifier = Modifier.clickable { onEdit() })
        Text(text = "Delete", modifier = Modifier.clickable { onDelete() })
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BatchScheduleDialog(
    workoutId: UUID,
    existingSchedules: List<WorkoutSchedule>,
    onDismiss: () -> Unit,
    onSave: (List<WorkoutSchedule>) -> Unit
) {
    val context = LocalContext.current
    val selectedTabIndex = rememberSaveable { mutableStateOf(0) }

    val labelPrefixState = rememberSaveable { mutableStateOf("Schedule") }
    val isEnabledState = rememberSaveable { mutableStateOf(true) }

    val startHourState = rememberSaveable { mutableIntStateOf(8) }
    val startMinuteState = rememberSaveable { mutableIntStateOf(0) }
    val endHourState = rememberSaveable { mutableIntStateOf(16) }
    val endMinuteState = rememberSaveable { mutableIntStateOf(0) }

    val currentPickerMode = remember { mutableStateOf("") } // "start" or "end"
    val showTimePicker = remember { mutableStateOf(false) }
    val timePickerState = rememberTimePickerState(initialHour = 8, initialMinute = 0)

    val intervalHoursState = rememberSaveable { mutableStateOf("0") }
    val intervalMinutesState = rememberSaveable { mutableStateOf("30") }

    val daysOfWeekState = rememberSaveable { mutableIntStateOf(0) }

    val datePickerState = rememberDatePickerState(initialSelectedDateMillis = System.currentTimeMillis())
    val showDatePicker = remember { mutableStateOf(false) }

    StandardDialog(
        onDismissRequest = onDismiss,
        title = "Add multiple schedules",
        body = {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(Spacing.sm)
            ) {
                TabRow(
                    contentColor = MaterialTheme.colorScheme.background,
                    selectedTabIndex = selectedTabIndex.value,
                    indicator = { tabPositions ->
                        TabRowDefaults.Indicator(
                            Modifier.tabIndicatorOffset(tabPositions[selectedTabIndex.value]),
                            color = MaterialTheme.colorScheme.primary,
                            height = 2.dp
                        )
                    }
                ) {
                    Tab(
                        modifier = Modifier.background(MaterialTheme.colorScheme.background),
                        selected = selectedTabIndex.value == 0,
                        onClick = { selectedTabIndex.value = 0 },
                        text = { Text("Recurring") },
                        selectedContentColor = MaterialTheme.colorScheme.primary,
                        unselectedContentColor = MaterialTheme.colorScheme.onBackground,
                        interactionSource = object : MutableInteractionSource {
                            override val interactions: Flow<Interaction> = emptyFlow()

                            override suspend fun emit(interaction: Interaction) {
                                // Empty implementation
                            }

                            override fun tryEmit(interaction: Interaction): Boolean = true
                        }
                    )
                    Tab(
                        modifier = Modifier.background(MaterialTheme.colorScheme.background),
                        selected = selectedTabIndex.value == 1,
                        onClick = { selectedTabIndex.value = 1 },
                        text = { Text("One-time") },
                        selectedContentColor = MaterialTheme.colorScheme.primary,
                        unselectedContentColor = MaterialTheme.colorScheme.onBackground,
                        interactionSource = object : MutableInteractionSource {
                            override val interactions: Flow<Interaction> = emptyFlow()

                            override suspend fun emit(interaction: Interaction) {
                                // Empty implementation
                            }

                            override fun tryEmit(interaction: Interaction): Boolean = true
                        }
                    )
                }

                Spacer(Modifier.height(Spacing.lg))

                OutlinedTextField(
                    value = labelPrefixState.value,
                    onValueChange = { labelPrefixState.value = it },
                    label = { Text("Label prefix", style = MaterialTheme.typography.labelLarge) },
                    modifier = Modifier.fillMaxWidth()
                )

                Spacer(Modifier.height(Spacing.lg))

                Text("Time range", style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(Spacing.sm))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("From")
                    Spacer(Modifier.width(Spacing.sm))
                    Button(onClick = {
                        timePickerState.hour = startHourState.intValue
                        timePickerState.minute = startMinuteState.intValue
                        currentPickerMode.value = "start"
                        showTimePicker.value = true
                    }) { Text("${startHourState.intValue}:${startMinuteState.intValue.toString().padStart(2, '0')}") }

                    Spacer(Modifier.width(Spacing.lg))

                    Text("To")
                    Spacer(Modifier.width(Spacing.sm))
                    Button(onClick = {
                        timePickerState.hour = endHourState.intValue
                        timePickerState.minute = endMinuteState.intValue
                        currentPickerMode.value = "end"
                        showTimePicker.value = true
                    }) { Text("${endHourState.intValue}:${endMinuteState.intValue.toString().padStart(2, '0')}") }
                }

                Spacer(Modifier.height(Spacing.lg))

                Text("Interval", style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(Spacing.sm))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    OutlinedTextField(
                        value = intervalHoursState.value,
                        onValueChange = { v -> if (v.isEmpty() || v.all { it.isDigit() }) intervalHoursState.value = v },
                        label = { Text("Hours", style = MaterialTheme.typography.labelLarge) },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.weight(1f)
                    )
                    Spacer(Modifier.width(Spacing.md))
                    OutlinedTextField(
                        value = intervalMinutesState.value,
                        onValueChange = { v -> if (v.isEmpty() || v.all { it.isDigit() }) intervalMinutesState.value = v },
                        label = { Text("Minutes", style = MaterialTheme.typography.labelLarge) },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.weight(1f)
                    )
                }

                Spacer(Modifier.height(Spacing.lg))

                if (selectedTabIndex.value == 1) {
                    val date = datePickerState.selectedDateMillis?.let {
                        Instant.ofEpochMilli(it).atZone(ZoneId.systemDefault()).toLocalDate()
                    } ?: LocalDate.now()
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("Date", style = MaterialTheme.typography.titleMedium)
                        Spacer(Modifier.width(Spacing.md))
                        Button(onClick = { showDatePicker.value = true }) { Text(date.toString()) }
                    }
                } else {
                    Text("Days of week", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(Spacing.sm))
                    WeekdaySelectionRow(
                        days = listOf("Mon", "Tue", "Wed", "Thu"),
                        bitValues = listOf(2, 4, 8, 16),
                        daysOfWeekState = daysOfWeekState
                    )
                    WeekdaySelectionRow(
                        days = listOf("Fri", "Sat", "Sun", ""),
                        bitValues = listOf(32, 64, 1, 0),
                        daysOfWeekState = daysOfWeekState,
                        showLastCheckbox = false
                    )
                }

                Spacer(Modifier.height(Spacing.lg))

                ListItem(
                    colors = ListItemDefaults.colors().copy(containerColor = Color.Transparent),
                    headlineContent = { Text("Enable all", style = MaterialTheme.typography.bodyLarge) },
                    trailingContent = {
                        Switch(
                            checked = isEnabledState.value,
                            onCheckedChange = { isEnabledState.value = it }
                        )
                    }
                )
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            }
        },
        confirmText = "Save",
        onConfirm = {
            val list = mutableListOf<WorkoutSchedule>()
            val startTotal = startHourState.intValue * 60 + startMinuteState.intValue
            val endTotal = endHourState.intValue * 60 + endMinuteState.intValue
            val interval = ((intervalHoursState.value.toIntOrNull() ?: 0) * 60 + (intervalMinutesState.value.toIntOrNull()
                ?: 30)).coerceAtLeast(1)

            var t = startTotal
            var count = 1
            while (t <= endTotal) {
                val hour = t / 60
                val minute = t % 60
                val specificDate = if (selectedTabIndex.value == 1) {
                    datePickerState.selectedDateMillis?.let {
                        Instant.ofEpochMilli(it).atZone(ZoneId.systemDefault()).toLocalDate()
                    }
                } else null

                list.add(
                    WorkoutSchedule(
                        id = UUID.randomUUID(),
                        workoutId = workoutId,
                        label = "${labelPrefixState.value} $count",
                        hour = hour,
                        minute = minute,
                        isEnabled = isEnabledState.value,
                        daysOfWeek = if (selectedTabIndex.value == 0) daysOfWeekState.intValue else 0,
                        specificDate = specificDate,
                        hasExecuted = false
                    )
                )

                t += interval
                count++
            }

            // Check for conflicts
            val conflicts = ScheduleConflictChecker.checkScheduleConflicts(
                newSchedules = list,
                existingSchedules = existingSchedules
            )

            if (conflicts.isNotEmpty()) {
                val errorMessage = ScheduleConflictChecker.formatConflictMessage(conflicts)
                Toast.makeText(context, errorMessage, Toast.LENGTH_LONG).show()
            } else {
                onSave(list)
            }
        },
        dismissText = "Cancel",
        onDismissButton = onDismiss
    )

    if (showTimePicker.value) {
        TimePickerDialog(
            onDismiss = { showTimePicker.value = false },
            onConfirm = {
                if (currentPickerMode.value == "start") {
                    startHourState.intValue = timePickerState.hour
                    startMinuteState.intValue = timePickerState.minute
                } else if (currentPickerMode.value == "end") {
                    endHourState.intValue = timePickerState.hour
                    endMinuteState.intValue = timePickerState.minute
                }
                showTimePicker.value = false
            },
            timePickerState = timePickerState
        )
    }

    if (showDatePicker.value) {
        DatePickerDialog(
            onDismissRequest = { showDatePicker.value = false },
            confirmButton = {
                DialogTextButton(
                    text = "OK",
                    onClick = { showDatePicker.value = false }
                )
            },
            dismissButton = {
                DialogTextButton(
                    text = "Cancel",
                    onClick = { showDatePicker.value = false }
                )
            }
        ) { DatePicker(state = datePickerState) }
    }
}


