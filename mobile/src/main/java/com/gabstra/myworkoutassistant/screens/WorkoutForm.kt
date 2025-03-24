package com.gabstra.myworkoutassistant.screens

import com.gabstra.myworkoutassistant.shared.Workout
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.DatePicker
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
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TimePicker
import androidx.compose.material3.TimePickerState
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.material3.rememberTimePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.health.connect.client.records.ExerciseSessionRecord
import com.gabstra.myworkoutassistant.WorkoutTypes
import com.gabstra.myworkoutassistant.composables.DarkModeContainer
import com.gabstra.myworkoutassistant.shared.WorkoutSchedule
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
    val schedules = remember { mutableStateOf(existingSchedules.toMutableList()) }
    val showScheduleDialog = remember { mutableStateOf(false) }
    val currentEditingSchedule = remember { mutableStateOf<WorkoutSchedule?>(null) }

    Scaffold(
        topBar = {
            DarkModeContainer(whiteOverlayAlpha =.1f, isRounded = false) {
                TopAppBar(
                    colors = TopAppBarDefaults.topAppBarColors(containerColor = Color.Transparent),
                    title = {
                        Text(
                            modifier = Modifier
                                .fillMaxWidth()
                                .basicMarquee(iterations = Int.MAX_VALUE),
                            textAlign = TextAlign.Center,
                            text = if(workout == null) "Insert Workout" else "Edit Workout"
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
                        IconButton(modifier = Modifier.alpha(0f), onClick = {}) {
                            Icon(
                                imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                                contentDescription = "Back"
                            )
                        }
                    }
                )
            }
        }
    ){
            it ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(it),
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
                        modifier = Modifier.background(MaterialTheme.colorScheme.surfaceContainerHigh)
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
                    colors =  CheckboxDefaults.colors().copy(
                        checkedCheckmarkColor =  MaterialTheme.colorScheme.background
                    )
                )
                Text(text = "Use Polar Device")
            }

            // Workout Schedule Section
            Card(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerHigh)
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
                    
                    // Add schedule button
                    Button(
                        onClick = {
                            currentEditingSchedule.value = null
                            showScheduleDialog.value = true
                        },
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(top = 8.dp)
                    ) {
                        Text("Add Schedule")
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
                        id  = workout?.id ?: java.util.UUID.randomUUID(),
                        name = workoutNameState.value.trim(),
                        description = workoutDescriptionState.value.trim(),
                        workoutComponents = workout?.workoutComponents ?: listOf(),
                        usePolarDevice = usePolarDeviceState.value,
                        creationDate = LocalDate.now(),
                        order =  workout?.order ?: 0,
                        timesCompletedInAWeek = timesCompletedInAWeekState.value.toIntOrNull(),
                        globalId = workout?.globalId ?: java.util.UUID.randomUUID(),
                        type = selectedWorkoutType.value
                    )

                    // Call the callback to insert/update the workout with schedules
                    onWorkoutUpsert(newWorkout, schedules.value)
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp)
            ) {
                if(workout==null) Text("Insert Workout") else Text("Edit Workout")
            }

            // Cancel button
            Button(
                colors = ButtonDefaults.buttonColors(contentColor = MaterialTheme.colorScheme.background),
                onClick = {
                    onCancel()
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp)
            ) {
                Text("Cancel")
            }
        }
    }
    
    // Schedule Dialog
    if (showScheduleDialog.value) {
        ScheduleDialog(
            schedule = currentEditingSchedule.value,
            workoutId = workout?.id ?: UUID.randomUUID(),
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
                    .padding(16.dp)
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
            TextButton(onClick = onDismiss) {
                Text("Cancel")
            }
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
                TextButton(onClick = { showDatePicker.value = false }) {
                    Text("Cancel")
                }
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
            Text(buttonText)
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
            TextButton(onClick = onDismiss) { Text("Cancel") }
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
            verticalAlignment = Alignment.CenterVertically
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
            
            // Edit button
            IconButton(onClick = onEdit) {
                Text("Edit")
            }
            
            // Delete button
            IconButton(onClick = onDelete) {
                Text("Delete")
            }
        }
    }
}
