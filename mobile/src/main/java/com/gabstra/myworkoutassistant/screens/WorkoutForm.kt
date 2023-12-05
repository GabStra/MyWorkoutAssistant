package com.gabstra.myworkoutassistant.screens

import com.gabstra.myworkoutassistant.shared.Workout
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable

import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp


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
    val restTimeState = remember { mutableStateOf(workout?.restTimeInSec ?: 0) }

    /*
    val showDeleteDialog = remember { mutableStateOf(false) }

    if (showDeleteDialog.value) {
        AlertDialog(
            onDismissRequest = {
                // Dismiss the dialog if the user cancels
                showDeleteDialog.value = false
            },
            title = {
                Text("Delete Workout")
            },
            text = {
                Text("Are you sure you want to delete this workout?")
            },
            confirmButton = {
                Button(
                    onClick = {
                        // Call the callback to delete the workout
                        onDelete()
                        showDeleteDialog.value = false
                    }
                ) {
                    Text("Yes")
                }
            },
            dismissButton = {
                Button(
                    onClick = {
                        // Dismiss the dialog if the user cancels
                        showDeleteDialog.value = false
                    }
                ) {
                    Text("No")
                }
            }
        )
    }*/

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

            //add a dropdown to choose the type of workout component




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

            // Rest time field
            OutlinedTextField(
                value = restTimeState.value.toString(),
                onValueChange = {
                    // Filter out non-numeric characters and limit the length
                    restTimeState.value = it.toIntOrNull() ?: 0
                },
                label = { Text("Rest Time (in seconds)") },
                keyboardOptions = KeyboardOptions.Default.copy(keyboardType = KeyboardType.Number),
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp)
            )

            // Submit button
            Button(
                onClick = {
                    val newWorkout = Workout(
                        name = workoutNameState.value,
                        description = workoutDescriptionState.value,
                        restTimeInSec = restTimeState.value,
                        workoutComponents = workout?.workoutComponents ?: listOf()
                    )

                    // Call the callback to insert/update the workout
                    onWorkoutUpsert(newWorkout)

                    // Clear form fields
                    workoutNameState.value = ""
                    workoutDescriptionState.value = ""
                    restTimeState.value = 0
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
                    // Call the callback to cancel the insertion/update
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