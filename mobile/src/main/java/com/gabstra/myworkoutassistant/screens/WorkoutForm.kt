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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDefaults
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TimePicker
import androidx.compose.material3.TimePickerState
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.material3.rememberTimePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.health.connect.client.records.ExerciseSessionRecord
import com.gabstra.myworkoutassistant.WorkoutTypes
import com.gabstra.myworkoutassistant.composables.CustomOutlinedButton
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.shared.DarkGray
import com.gabstra.myworkoutassistant.shared.LightGray
import com.gabstra.myworkoutassistant.shared.MediumGray
import com.gabstra.myworkoutassistant.shared.MediumLightGray
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutSchedule
import com.gabstra.myworkoutassistant.verticalColumnScrollbar
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.util.Locale
import java.util.UUID


@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WorkoutForm(
    onWorkoutUpsert: (Workout, List<WorkoutSchedule>) -> Unit,
    onCancel: () -> Unit,
    workout: Workout? = null, // Add workout parameter with default value null
    existingSchedules: List<WorkoutSchedule> = emptyList()
) {
    // Mutable state for form fields
    val workoutNameState = remember { mutableStateOf(workout?.name ?: "") }
    val workoutDescriptionState = remember { mutableStateOf(workout?.description ?: "") }
    val timesCompletedInAWeekState = remember { mutableStateOf(workout?.timesCompletedInAWeek?.toString() ?: "0") }
    val usePolarDeviceState = remember { mutableStateOf(workout?.usePolarDevice ?: false) }

    val selectedWorkoutType = remember { mutableStateOf(workout?.type ?: ExerciseSessionRecord.EXERCISE_TYPE_STRENGTH_TRAINING) }
    val expanded = remember { mutableStateOf(false) }
    
    // Schedule states
    val schedules = remember(existingSchedules) { mutableStateOf(existingSchedules.toMutableList()) }
    val showScheduleDialog = remember { mutableStateOf(false) }
    val currentEditingSchedule = remember { mutableStateOf<WorkoutSchedule?>(null) }

    val newGlobalId = remember { UUID.randomUUID() }

    val showBatchScheduleDialog = remember { mutableStateOf(false) }

    Scaffold(
        topBar = {
            TopAppBar(
                modifier = Modifier.drawBehind {
                    drawLine(
                        color = MediumLightGray,
                        start = Offset(0f, size.height),
                        end = Offset(size.width, size.height),
                        strokeWidth = 1.dp.toPx()
                    )
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Color.Transparent),
                title = {
                    Text(
                        modifier = Modifier
                            .fillMaxWidth()
                            .basicMarquee(iterations = Int.MAX_VALUE),
                        textAlign = TextAlign.Center,
                        text = if(workout == null) "Insert Workout" else "Edit Workout",
                        color = LightGray,
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onCancel) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "Back"
                        )
                    }
                },
                actions = {
                    IconButton(modifier = Modifier.alpha(0f), onClick = {onCancel()}) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "Back"
                        )
                    }
                }
            )
        }
    ){
            it ->
        val scrollState = rememberScrollState()

        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(it)
                .padding(top = 10.dp)
                .verticalColumnScrollbar(scrollState)
                .verticalScroll(scrollState)
                .padding(horizontal = 15.dp),
            verticalArrangement = Arrangement.Center,
        ) {
            // Workout name field
            OutlinedTextField(
                value = workoutNameState.value,
                onValueChange = { workoutNameState.value = it },
                label = { Text("Workout Name") },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp)
            )

            // Workout description field
            OutlinedTextField(
                value = workoutDescriptionState.value,
                onValueChange = { workoutDescriptionState.value = it },
                label = { Text("Description") },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(120.dp)
                    .padding(8.dp)
            )

            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp)
            ) {
                Text(text = "Type:")
                Box(modifier = Modifier.fillMaxWidth()) {
                    Text(
                        text = WorkoutTypes.GetNameFromInt(selectedWorkoutType.value),
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { expanded.value = true }
                            .padding(8.dp)
                    )
                    DropdownMenu(
                        expanded = expanded.value,
                        onDismissRequest = { expanded.value = false },
                        modifier = Modifier.background(MaterialTheme.colorScheme.background),
                        border = BorderStroke(1.dp, MediumGray)
                    ) {
                        WorkoutTypes.WORKOUT_TYPE_STRING_TO_INT_MAP.keys.forEach { key ->
                            DropdownMenuItem(
                                onClick = {
                                    selectedWorkoutType.value =  WorkoutTypes.WORKOUT_TYPE_STRING_TO_INT_MAP[key]!!
                                    expanded.value = false
                                },
                                text = {
                                    Text(text =  key.replace('_', ' ').capitalize(Locale.ROOT))
                                }
                            )
                        }
                    }
                }
            }

            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp),
            ) {
                OutlinedTextField(
                    value = timesCompletedInAWeekState.value,
                    onValueChange = { input ->
                        if (input.isEmpty() || input.all { it -> it.isDigit() }) {
                            timesCompletedInAWeekState.value = input
                        }
                    },
                    label = { Text("Objective per week") },
                    keyboardOptions = KeyboardOptions.Default.copy(keyboardType = KeyboardType.Number),
                    modifier = Modifier
                        .fillMaxWidth()
                )
            }

            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp)
            ) {
                Checkbox(
                    checked = usePolarDeviceState.value,
                    onCheckedChange = { usePolarDeviceState.value = it },
                    colors = CheckboxDefaults.colors().copy(
                        checkedCheckmarkColor = LightGray,
                        uncheckedBorderColor = MaterialTheme.colorScheme.primary
                    )
                )
                Text(text = "Use Polar Device")
            }

            // Workout Schedule Section
            StyledCard(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp),
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(16.dp)
                ) {
                    Text(
                        text = "Workout Schedule",
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                        modifier = Modifier.padding(bottom = 8.dp)
                    )
                    
                    // Display existing schedules
                    if (schedules.value.isEmpty()) {
                        Text(
                            text = "No schedules set",
                            style = MaterialTheme.typography.bodyMedium,
                            modifier = Modifier.padding(vertical = 8.dp)
                        )
                    } else {
                        Column {
                            schedules.value.forEachIndexed { index, schedule ->
                                ScheduleListItem(
                                    schedule = schedule,
                                    index = index,
                                    onEdit = {
                                        currentEditingSchedule.value = schedule
                                        showScheduleDialog.value = true
                                    },
                                    onDelete = {
                                        val updatedSchedules = schedules.value.toMutableList()
                                        updatedSchedules.removeAt(index)
                                        schedules.value = updatedSchedules
                                    }
                                )
                            }
                        }
                    }

                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(top = 8.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        Button(
                            onClick = {
                                currentEditingSchedule.value = null
                                showScheduleDialog.value = true
                            },
                            modifier = Modifier.weight(1f)
                        ) {
                            Text("Add Single", color = DarkGray)
                        }

                        Button(
                            onClick = {
                                showBatchScheduleDialog.value = true
                            },
                            modifier = Modifier.weight(1f)
                        ) {
                            Text("Add Multiple", color = DarkGray)
                        }
                    }
                }
            }
            
            // Submit button
            Button(
                colors = ButtonDefaults.buttonColors(contentColor = MaterialTheme.colorScheme.background),
                onClick = {
                    if (workoutNameState.value.isBlank()) {
                        return@Button
                    }

                    val newWorkout = Workout(
                        id  = workout?.id ?: UUID.randomUUID(),
                        name = workoutNameState.value.trim(),
                        description = workoutDescriptionState.value.trim(),
                        workoutComponents = workout?.workoutComponents ?: listOf(),
                        usePolarDevice = usePolarDeviceState.value,
                        creationDate = LocalDate.now(),
                        order =  workout?.order ?: 0,
                        timesCompletedInAWeek = timesCompletedInAWeekState.value.toIntOrNull(),
                        globalId = workout?.globalId ?: newGlobalId,
                        type = selectedWorkoutType.value
                    )

                    // Call the callback to insert/update the workout with schedules
                    onWorkoutUpsert(newWorkout, schedules.value)
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp)
            ) {
                if(workout==null) Text("Insert Workout", color = DarkGray) else Text("Edit Workout", color = DarkGray)
            }

            CustomOutlinedButton(
                text = "Cancel",
                color = MediumGray,
                onClick = {
                    onCancel()
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp)
            )
        }
    }
    
    // Schedule Dialog
    if (showScheduleDialog.value) {
        ScheduleDialog(
            schedule = currentEditingSchedule.value,
            workoutId = workout?.globalId ?: newGlobalId,
            onDismiss = { showScheduleDialog.value = false },
            onSave = { newSchedule ->
                val updatedSchedules = schedules.value.toMutableList()
                
                if (currentEditingSchedule.value != null) {
                    // Update existing schedule
                    val index = updatedSchedules.indexOfFirst { it.id == newSchedule.id }
                    if (index != -1) {
                        updatedSchedules[index] = newSchedule
                    }
                } else {
                    // Add new schedule
                    updatedSchedules.add(newSchedule)
                }
                
                schedules.value = updatedSchedules
                showScheduleDialog.value = false
            }
        )
    }

    // Add this right after the single ScheduleDialog
// Batch Schedule Dialog
    if (showBatchScheduleDialog.value) {
        BatchScheduleDialog(
            workoutId = workout?.globalId ?: newGlobalId,
            onDismiss = { showBatchScheduleDialog.value = false },
            onSave = { newSchedules ->
                val updatedSchedules = schedules.value.toMutableList()
                updatedSchedules.addAll(newSchedules)
                schedules.value = updatedSchedules
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
    onDismiss: () -> Unit,
    onSave: (WorkoutSchedule) -> Unit
) {
    val isEditing = schedule != null
    
    // Schedule state
    val labelState = remember { mutableStateOf(schedule?.label ?: "") }
    val hourState = remember { mutableIntStateOf(schedule?.hour ?: 8) }
    val minuteState = remember { mutableIntStateOf(schedule?.minute ?: 0) }
    val isEnabledState = remember { mutableStateOf(schedule?.isEnabled ?: true) }
    
    // Days of week state (bit field)
    val daysOfWeekState = remember { mutableIntStateOf(schedule?.daysOfWeek ?: 0) }
    
    // Specific date vs recurring
    val useSpecificDate = remember { mutableStateOf(schedule?.specificDate != null) }
    
    // Date picker state
    val datePickerState = rememberDatePickerState(
        initialSelectedDateMillis = schedule?.specificDate?.atStartOfDay(ZoneId.systemDefault())?.toInstant()?.toEpochMilli()
            ?: System.currentTimeMillis()
    )
    val showDatePicker = remember { mutableStateOf(false) }
    
    // Time picker state
    val timePickerState = rememberTimePickerState(
        initialHour = schedule?.hour ?: 8,
        initialMinute = schedule?.minute ?: 0
    )
    val showTimePicker = remember { mutableStateOf(false) }
    
    // Dialog content
    androidx.compose.material3.AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (isEditing) "Edit Schedule" else "Add Schedule") },
        text = {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp)
            ) {
                // Label field
                OutlinedTextField(
                    value = labelState.value,
                    onValueChange = { labelState.value = it },
                    label = { Text("Label (optional)") },
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(bottom = 8.dp)
                )
                
                // Time selection
                LabeledButton(
                    label = "Time:",
                    buttonText = "${hourState.intValue}:${minuteState.intValue.toString().padStart(2, '0')}",
                    onClick = { showTimePicker.value = true }
                )
                
                // Toggle between specific date and recurring
                LabeledSwitch(
                    label = "Use specific date:",
                    checked = useSpecificDate.value,
                    onCheckedChange = { useSpecificDate.value = it }
                )
                
                // Date selection or days of week
                if (useSpecificDate.value) {
                    // Specific date
                    val date = datePickerState.selectedDateMillis?.let {
                        Instant.ofEpochMilli(it).atZone(ZoneId.systemDefault()).toLocalDate()
                    } ?: LocalDate.now()
                    
                    LabeledButton(
                        label = "Date:",
                        buttonText = date.toString(),
                        onClick = { showDatePicker.value = true }
                    )
                } else {
                    // Days of week
                    Text(
                        text = "Days of week:",
                        modifier = Modifier.padding(vertical = 8.dp)
                    )
                    
                    // First row: Sun-Wed
                    WeekdaySelectionRow(
                        days = listOf("Sun", "Mon", "Tue", "Wed"),
                        bitValues = listOf(1, 2, 4, 8),
                        daysOfWeekState = daysOfWeekState
                    )
                    
                    // Second row: Thu-Sat + empty space
                    WeekdaySelectionRow(
                        days = listOf("Thu", "Fri", "Sat", ""),
                        bitValues = listOf(16, 32, 64, 0),
                        daysOfWeekState = daysOfWeekState,
                        showLastCheckbox = false
                    )
                }
                
                // Enabled toggle
                LabeledCheckbox(
                    label = "Enabled:",
                    checked = isEnabledState.value,
                    onCheckedChange = { isEnabledState.value = it }
                )
            }
        },
        confirmButton = {
            TextButton(
                onClick = {
                    val specificDate = if (useSpecificDate.value) {
                        datePickerState.selectedDateMillis?.let {
                            Instant.ofEpochMilli(it).atZone(ZoneId.systemDefault()).toLocalDate()
                        }
                    } else {
                        null
                    }
                    
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
                    
                    onSave(newSchedule)
                }
            ) {
                Text("Save")
            }
        },
        dismissButton = {
            CustomOutlinedButton(
                text = "Cancel",
                color = MediumGray,
                onClick = onDismiss,
            )
        }
    )
    
    // Time picker dialog
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
    
    // Date picker dialog
    if (showDatePicker.value) {
        DatePickerDialog(
            onDismissRequest = { showDatePicker.value = false },
            confirmButton = {
                TextButton(onClick = { showDatePicker.value = false }) {
                    Text("OK")
                }
            },
            dismissButton = {
                CustomOutlinedButton(
                    text = "Cancel",
                    color = MediumGray,
                    onClick = { showDatePicker.value = false },
                )
            }
        ) {
            DatePicker(state = datePickerState)
        }
    }
}

@Composable
fun LabeledButton(
    label: String,
    buttonText: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(label)
        Spacer(modifier = Modifier.width(8.dp))
        Button(onClick = onClick) {
            Text(buttonText, color = LightGray)
        }
    }
}

@Composable
fun LabeledSwitch(
    label: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
    modifier: Modifier = Modifier
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(label)
        Spacer(modifier = Modifier.width(8.dp))
        Switch(
            checked = checked,
            onCheckedChange = onCheckedChange
        )
    }
}

@Composable
fun LabeledCheckbox(
    label: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
    modifier: Modifier = Modifier
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(label)
        Spacer(modifier = Modifier.width(8.dp))
        Checkbox(
            checked = checked,
            onCheckedChange = onCheckedChange
        )
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
    androidx.compose.material3.AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Select Time") },
        text = { TimePicker(state = timePickerState) },
        confirmButton = {
            TextButton(onClick = onConfirm) { Text("OK") }
        },
        dismissButton = {
            CustomOutlinedButton(
                text = "Cancel",
                color = MediumGray,
                onClick = onDismiss,
            )
        }
    )
}

@Composable
fun DayOfWeekCheckbox(
    day: String,
    isChecked: Boolean,
    onCheckedChange: (Boolean) -> Unit
) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(text = day, style = MaterialTheme.typography.bodySmall)
        Checkbox(
            checked = isChecked,
            onCheckedChange = onCheckedChange
        )
    }
}

// Helper function to convert bit field to readable days string
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
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp),
        shape = RoundedCornerShape(8.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerLow)
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(5.dp)
        ) {
            Column(modifier = Modifier.weight(1f)) {
                // Display schedule info
                Text(
                    text = if (schedule.label.isNotEmpty()) schedule.label else "Schedule ${index + 1}",
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.Bold
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

            Text(modifier = Modifier.clickable {
                onEdit()
            },
                text= "Edit"
            )

            Text(modifier = Modifier.clickable {
                onDelete()
            },
                text= "Delete"
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BatchScheduleDialog(
    workoutId: UUID,
    onDismiss: () -> Unit,
    onSave: (List<WorkoutSchedule>) -> Unit
) {
    // Tab selection
    val selectedTabIndex = remember { mutableStateOf(0) }

    // Shared state
    val labelPrefixState = remember { mutableStateOf("Schedule") }
    val isEnabledState = remember { mutableStateOf(true) }

    // Time range state
    val startHourState = remember { mutableIntStateOf(8) }
    val startMinuteState = remember { mutableIntStateOf(0) }
    val endHourState = remember { mutableIntStateOf(16) }
    val endMinuteState = remember { mutableIntStateOf(0) }

    // Time picker states
    val currentPickerMode = remember { mutableStateOf("") } // "start" or "end"
    val showTimePicker = remember { mutableStateOf(false) }
    val timePickerState = rememberTimePickerState(initialHour = 8, initialMinute = 0)

    // Interval state
    val intervalHoursState = remember { mutableStateOf("0") }
    val intervalMinutesState = remember { mutableStateOf("30") }

    // Days of week state (bit field)
    val daysOfWeekState = remember { mutableIntStateOf(0) }

    // Date picker for one-time schedules
    val datePickerState = rememberDatePickerState(initialSelectedDateMillis = System.currentTimeMillis())
    val showDatePicker = remember { mutableStateOf(false) }

    // Dialog content
    androidx.compose.material3.AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Add Multiple Schedules") },
        text = {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = 8.dp)
            ) {
                // Tab selection for schedule type
                TabRow(selectedTabIndex = selectedTabIndex.value) {
                    Tab(
                        selected = selectedTabIndex.value == 0,
                        onClick = { selectedTabIndex.value = 0 },
                        text = { Text("Recurring") }
                    )
                    Tab(
                        selected = selectedTabIndex.value == 1,
                        onClick = { selectedTabIndex.value = 1 },
                        text = { Text("One-time") }
                    )
                }

                Spacer(modifier = Modifier.height(16.dp))

                // Label prefix field
                OutlinedTextField(
                    value = labelPrefixState.value,
                    onValueChange = { labelPrefixState.value = it },
                    label = { Text("Label Prefix") },
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(bottom = 8.dp)
                )

                // Time range selection
                Text(
                    text = "Time Range:",
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.padding(bottom = 4.dp)
                )

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text("From:")
                    Spacer(modifier = Modifier.width(8.dp))
                    Button(onClick = {
                        timePickerState.hour = startHourState.intValue
                        timePickerState.minute = startMinuteState.intValue
                        currentPickerMode.value = "start"
                        showTimePicker.value = true
                    }) {
                        Text("${startHourState.intValue}:${startMinuteState.intValue.toString().padStart(2, '0')}")
                    }

                    Spacer(modifier = Modifier.width(16.dp))

                    Text("To:")
                    Spacer(modifier = Modifier.width(8.dp))
                    Button(onClick = {
                        timePickerState.hour = endHourState.intValue
                        timePickerState.minute = endMinuteState.intValue
                        currentPickerMode.value = "end"
                        showTimePicker.value = true
                    }) {
                        Text("${endHourState.intValue}:${endMinuteState.intValue.toString().padStart(2, '0')}")
                    }
                }

                Spacer(modifier = Modifier.height(16.dp))

                // Interval selection
                Text(
                    text = "Interval:",
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.padding(bottom = 4.dp)
                )

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    // Hours
                    OutlinedTextField(
                        value = intervalHoursState.value,
                        onValueChange = { value ->
                            if (value.isEmpty() || value.all { it.isDigit() }) {
                                intervalHoursState.value = value
                            }
                        },
                        label = { Text("Hours") },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.weight(1f)
                    )

                    Spacer(modifier = Modifier.width(8.dp))

                    // Minutes
                    OutlinedTextField(
                        value = intervalMinutesState.value,
                        onValueChange = { value ->
                            if (value.isEmpty() || value.all { it.isDigit() }) {
                                intervalMinutesState.value = value
                            }
                        },
                        label = { Text("Minutes") },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.weight(1f)
                    )
                }

                Spacer(modifier = Modifier.height(16.dp))

                // Specific date or days of week based on tab
                if (selectedTabIndex.value == 1) {
                    // Specific date for one-time schedules
                    val date = datePickerState.selectedDateMillis?.let {
                        Instant.ofEpochMilli(it).atZone(ZoneId.systemDefault()).toLocalDate()
                    } ?: LocalDate.now()

                    LabeledButton(
                        label = "Date:",
                        buttonText = date.toString(),
                        onClick = { showDatePicker.value = true }
                    )
                } else {
                    // Days of week for recurring schedules
                    Text(
                        text = "Days of week:",
                        modifier = Modifier.padding(bottom = 8.dp)
                    )

                    // First row: Sun-Wed
                    WeekdaySelectionRow(
                        days = listOf( "Mon", "Tue", "Wed","Thu"),
                        bitValues = listOf(2, 4, 8, 16),
                        daysOfWeekState = daysOfWeekState
                    )

                    // Second row: Thu-Sat + empty space
                    WeekdaySelectionRow(
                        days = listOf("Fri", "Sat", "Sun"),
                        bitValues = listOf(32, 64, 1),
                        daysOfWeekState = daysOfWeekState,
                        showLastCheckbox = false
                    )
                }

                // Enabled toggle
                LabeledCheckbox(
                    label = "Enable all schedules:",
                    checked = isEnabledState.value,
                    onCheckedChange = { isEnabledState.value = it }
                )
            }
        },
        confirmButton = {
            TextButton(
                onClick = {
                    val schedules = mutableListOf<WorkoutSchedule>()

                    // Calculate total minutes in each time
                    val startTotalMinutes = startHourState.intValue * 60 + startMinuteState.intValue
                    val endTotalMinutes = endHourState.intValue * 60 + endMinuteState.intValue

                    // Calculate interval in minutes
                    val intervalMinutes = (intervalHoursState.value.toIntOrNull() ?: 0) * 60 +
                            (intervalMinutesState.value.toIntOrNull() ?: 30)

                    // Ensure interval is at least 1 minute
                    val safeInterval = if (intervalMinutes < 1) 1 else intervalMinutes

                    var currentTime = startTotalMinutes
                    var count = 1

                    while (currentTime <= endTotalMinutes) {
                        val hour = currentTime / 60
                        val minute = currentTime % 60

                        val specificDate = if (selectedTabIndex.value == 1) {
                            datePickerState.selectedDateMillis?.let {
                                Instant.ofEpochMilli(it).atZone(ZoneId.systemDefault()).toLocalDate()
                            }
                        } else {
                            null
                        }

                        val newSchedule = WorkoutSchedule(
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

                        schedules.add(newSchedule)

                        currentTime += safeInterval
                        count++
                    }

                    onSave(schedules)
                }
            ) {
                Text("Save")
            }
        },
        dismissButton = {
            CustomOutlinedButton(
                text = "Cancel",
                color = MediumGray,
                onClick = onDismiss,
            )
        }
    )

    // Time picker dialog
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

    // Date picker dialog
    if (showDatePicker.value) {
        DatePickerDialog(
            onDismissRequest = { showDatePicker.value = false },
            confirmButton = {
                TextButton(onClick = { showDatePicker.value = false }) {
                    Text("OK")
                }
            },
            dismissButton = {
                CustomOutlinedButton(
                    text = "Cancel",
                    color = MediumGray,
                    onClick = { showDatePicker.value = false },
                )
            }
        ) {
            DatePicker(
                state = datePickerState,
                colors =  DatePickerDefaults.colors().copy()
            )
        }
    }
}
