package com.gabstra.myworkoutassistant.screens

import com.gabstra.myworkoutassistant.shared.Workout
import androidx.compose.foundation.background
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
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
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
import com.gabstra.myworkoutassistant.formatSecondsToMinutesSeconds
import java.time.LocalDate


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
    val restTimeState = remember { mutableStateOf(workout?.restTimeInSec?.toString() ?: "0") }
    val timesCompletedInAWeekState = remember { mutableStateOf(workout?.timesCompletedInAWeek?.toString() ?: "0") }
    val usePolarDeviceState = remember { mutableStateOf(workout?.usePolarDevice ?: false) }


    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background) // Set the background color to black
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

            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp),
            ) {
                if(restTimeState.value.isNotEmpty()){
                    Text(formatSecondsToMinutesSeconds(restTimeState.value.toInt()))
                    Spacer(modifier = Modifier.height(15.dp))
                }
                // Rest time field
                OutlinedTextField(
                    value = restTimeState.value,
                    onValueChange = { input ->
                        if (input.isEmpty() || input.all { it -> it.isDigit() }) {
                            // Update the state only if the input is empty or all characters are digits
                            val inputValue = input.toIntOrNull()

                            if (inputValue != null && inputValue >= 3600) {
                                restTimeState.value = "3599"
                            } else {
                                restTimeState.value = input
                            }
                        }
                    },
                    label = { Text("Rest Time Between Exercises (in seconds)") },
                    keyboardOptions = KeyboardOptions.Default.copy(keyboardType = KeyboardType.Number),
                    modifier = Modifier
                        .fillMaxWidth()
                )
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
                            val inputValue = input.toIntOrNull()

                            if (inputValue != null && inputValue == 0) {
                                timesCompletedInAWeekState.value = "1"
                            } else {
                                timesCompletedInAWeekState.value = input
                            }
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
                )
                Text(text = "Use Polar Device")
            }

            // Submit button
            Button(
                onClick = {
                    if (workoutNameState.value.isBlank()) {
                        return@Button
                    }

                    val restTimeInSec = restTimeState.value.toIntOrNull() ?: 0
                    val newWorkout = Workout(
                        id  = workout?.id ?: java.util.UUID.randomUUID(),
                        name = workoutNameState.value.trim(),
                        description = workoutDescriptionState.value.trim(),
                        restTimeInSec = if (restTimeInSec >= 0) restTimeInSec else 0,
                        workoutComponents = workout?.workoutComponents ?: listOf(),
                        usePolarDevice = usePolarDeviceState.value,
                        creationDate = LocalDate.now(),
                        order =  workout?.order ?: 0,
                        timesCompletedInAWeek = timesCompletedInAWeekState.value.toIntOrNull()
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