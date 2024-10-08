package com.gabstra.myworkoutassistant.screens

import com.gabstra.myworkoutassistant.shared.Workout
import androidx.compose.foundation.background
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
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable

import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.health.connect.client.records.ExerciseSessionRecord
import com.gabstra.myworkoutassistant.WorkoutTypes
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

    Box(
        modifier = Modifier
            .fillMaxSize()
    ){
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(16.dp),
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
}