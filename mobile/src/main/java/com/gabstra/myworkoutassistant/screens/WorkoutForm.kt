package com.gabstra.myworkoutassistant.screens

import com.gabstra.myworkoutassistant.shared.Workout
import androidx.compose.foundation.background
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable

import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.health.connect.client.records.ExerciseSessionRecord
import com.gabstra.myworkoutassistant.WorkoutTypes
import com.gabstra.myworkoutassistant.composables.DarkModeContainer
import java.time.LocalDate
import java.util.Locale


@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WorkoutForm(
    onWorkoutUpsert: (Workout) -> Unit,
    onCancel: () -> Unit,
    workout: Workout? = null // Add workout parameter with default value null
) {
    // Mutable state for form fields
    val workoutNameState = remember { mutableStateOf(workout?.name ?: "") }
    val workoutDescriptionState = remember { mutableStateOf(workout?.description ?: "") }
    val timesCompletedInAWeekState = remember { mutableStateOf(workout?.timesCompletedInAWeek?.toString() ?: "0") }
    val usePolarDeviceState = remember { mutableStateOf(workout?.usePolarDevice ?: false) }

    val selectedWorkoutType = remember { mutableStateOf(workout?.type ?: ExerciseSessionRecord.EXERCISE_TYPE_STRENGTH_TRAINING) }
    val expanded = remember { mutableStateOf(false) }

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

                    // Call the callback to insert/update the workout
                    onWorkoutUpsert(newWorkout)
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
}package com.gabstra.myworkoutassistant.screens

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutSchedule
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.util.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WorkoutForm(
    onWorkoutUpsert: (Workout) -> Unit,
    onCancel: () -> Unit,
    workout: Workout? = null
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val db = AppDatabase.getDatabase(context)
    val workoutScheduleDao = db.workoutScheduleDao()
    
    // Existing form state
    var name by remember { mutableStateOf(workout?.name ?: "") }
    var description by remember { mutableStateOf(workout?.description ?: "") }
    var usePolarDevice by remember { mutableStateOf(workout?.usePolarDevice ?: false) }
    
    // New scheduling state
    var isScheduleEnabled by remember { mutableStateOf(false) }
    var selectedDaysOfWeek by remember { mutableStateOf(0) } // Bitmap for days
    var scheduleHour by remember { mutableStateOf(8) }
    var scheduleMinute by remember { mutableStateOf(0) }
    var existingSchedule by remember { mutableStateOf<WorkoutSchedule?>(null) }
    
    // Load existing schedule if editing
    LaunchedEffect(workout) {
        if (workout != null) {
            scope.launch {
                val schedule = workoutScheduleDao.getScheduleByWorkoutId(workout.id)
                if (schedule != null) {
                    existingSchedule = schedule
                    isScheduleEnabled = schedule.isEnabled
                    selectedDaysOfWeek = schedule.daysOfWeek
                    scheduleHour = schedule.hour
                    scheduleMinute = schedule.minute
                }
            }
        }
    }
    
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
            .verticalScroll(rememberScrollState()),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(
            text = if (workout == null) "Create New Workout" else "Edit Workout",
            style = MaterialTheme.typography.headlineMedium
        )
        
        Spacer(modifier = Modifier.height(16.dp))
        
        OutlinedTextField(
            value = name,
            onValueChange = { name = it },
            label = { Text("Workout Name") },
            modifier = Modifier.fillMaxWidth()
        )
        
        Spacer(modifier = Modifier.height(8.dp))
        
        OutlinedTextField(
            value = description,
            onValueChange = { description = it },
            label = { Text("Description") },
            modifier = Modifier.fillMaxWidth(),
            minLines = 3
        )
        
        Spacer(modifier = Modifier.height(16.dp))
        
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.fillMaxWidth()
        ) {
            Checkbox(
                checked = usePolarDevice,
                onCheckedChange = { usePolarDevice = it }
            )
            Text("Use Polar Device")
        }
        
        Spacer(modifier = Modifier.height(16.dp))
        
        // Workout Schedule Section
        Card(
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp)
        ) {
            Column(
                modifier = Modifier
                    .padding(16.dp)
                    .fillMaxWidth()
            ) {
                Text(
                    text = "Workout Schedule",
                    style = MaterialTheme.typography.titleMedium
                )
                
                Spacer(modifier = Modifier.height(8.dp))
                
                Row(
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Switch(
                        checked = isScheduleEnabled,
                        onCheckedChange = { isScheduleEnabled = it }
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    Text("Enable scheduling for this workout")
                }
                
                AnimatedVisibility(visible = isScheduleEnabled) {
                    Column {
                        Spacer(modifier = Modifier.height(16.dp))
                        
                        // Day of week selection
                        Text("Select days:", style = MaterialTheme.typography.bodyMedium)
                        Spacer(modifier = Modifier.height(8.dp))
                        
                        // Using a Row with 7 checkboxes for days of week
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween
                        ) {
                            val daysAbbrev = listOf("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
                            
                            daysAbbrev.forEachIndexed { index, day ->
                                val isSelected = (selectedDaysOfWeek and (1 shl index)) != 0
                                
                                Column(
                                    horizontalAlignment = Alignment.CenterHorizontally
                                ) {
                                    Text(day)
                                    Checkbox(
                                        checked = isSelected,
                                        onCheckedChange = { checked ->
                                            selectedDaysOfWeek = if (checked) {
                                                selectedDaysOfWeek or (1 shl index)
                                            } else {
                                                selectedDaysOfWeek and (1 shl index).inv()
                                            }
                                        }
                                    )
                                }
                            }
                        }
                        
                        Spacer(modifier = Modifier.height(16.dp))
                        
                        // Time picker
                        Text("Schedule time:", style = MaterialTheme.typography.bodyMedium)
                        Spacer(modifier = Modifier.height(8.dp))
                        
                        Row(
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            // Hour picker
                            OutlinedTextField(
                                value = scheduleHour.toString(),
                                onValueChange = { 
                                    val hour = it.toIntOrNull() ?: 0
                                    if (hour in 0..23) {
                                        scheduleHour = hour
                                    }
                                },
                                label = { Text("Hour") },
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                                modifier = Modifier.width(100.dp)
                            )
                            
                            Text(":", modifier = Modifier.padding(horizontal = 8.dp))
                            
                            // Minute picker
                            OutlinedTextField(
                                value = scheduleMinute.toString(),
                                onValueChange = { 
                                    val minute = it.toIntOrNull() ?: 0
                                    if (minute in 0..59) {
                                        scheduleMinute = minute
                                    }
                                },
                                label = { Text("Minute") },
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                                modifier = Modifier.width(100.dp)
                            )
                        }
                    }
                }
            }
        }
        
        Spacer(modifier = Modifier.height(24.dp))
        
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.End
        ) {
            TextButton(
                onClick = onCancel
            ) {
                Text("Cancel")
            }
            
            Spacer(modifier = Modifier.width(8.dp))
            
            Button(
                onClick = {
                    // Create or update the workout
                    val updatedWorkout = (workout?.copy(
                        name = name,
                        description = description,
                        usePolarDevice = usePolarDevice
                    ) ?: Workout(
                        id = UUID.randomUUID(),
                        name = name,
                        description = description,
                        workoutComponents = emptyList(),
                        order = 0,
                        enabled = true,
                        usePolarDevice = usePolarDevice,
                        creationDate = LocalDate.now()
                    ))
                    
                    // Save the workout first
                    onWorkoutUpsert(updatedWorkout)
                    
                    // Then save the schedule if enabled
                    if (isScheduleEnabled) {
                        val schedule = WorkoutSchedule(
                            id = existingSchedule?.id ?: UUID.randomUUID(),
                            workoutId = updatedWorkout.id,
                            label = name,
                            hour = scheduleHour,
                            minute = scheduleMinute,
                            isEnabled = true,
                            daysOfWeek = selectedDaysOfWeek,
                            specificDate = null,
                            hasExecuted = false
                        )
                        
                        scope.launch {
                            workoutScheduleDao.insert(schedule)
                        }
                    } else if (existingSchedule != null) {
                        // If scheduling was disabled but there was an existing schedule, disable it
                        scope.launch {
                            workoutScheduleDao.update(existingSchedule!!.copy(isEnabled = false))
                        }
                    }
                }
            ) {
                Text("Save")
            }
        }
    }
}
