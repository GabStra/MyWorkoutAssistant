package com.gabstra.myworkoutassistant

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable

import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ExerciseGroupForm(
    onWorkoutComponentUpsert: (WorkoutComponent) -> Unit,
    onCancel: () -> Unit,
    workoutComponent: WorkoutComponent? = null
) {
    // Mutable state for form fields
    val groupNameState = remember { mutableStateOf(workoutComponent?.name ?: "") }
    val setsState = remember { mutableStateOf(workoutComponent?.sets?.toString() ?: "") }
    val restTimeState = remember { mutableStateOf(workoutComponent?.restTimeInSec?.toString() ?: "") }
    // Assume ExerciseForm is a separate composable to handle exercise details
    val exercisesState = remember { mutableStateOf(workoutComponent?.exercises ?: listOf()) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        // Group name field
        OutlinedTextField(
            value = groupNameState.value,
            onValueChange = { groupNameState.value = it },
            label = { Text("Group Name") },
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp)
        )

        // Sets field
        OutlinedTextField(
            value = setsState.value,
            onValueChange = { setsState.value = it.filter { char -> char.isDigit() } },
            label = { Text("Sets") },
            keyboardOptions = KeyboardOptions.Default.copy(keyboardType = KeyboardType.Number),
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp)
        )

        // Rest time field
        OutlinedTextField(
            value = restTimeState.value,
            onValueChange = { restTimeState.value = it.filter { char -> char.isDigit() } },
            label = { Text("Rest Time (in seconds)") },
            keyboardOptions = KeyboardOptions.Default.copy(keyboardType = KeyboardType.Number),
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp)
        )

        // Submit button
        Button(
            onClick = {
                val newExerciseGroup = ExerciseGroup(
                    name = groupNameState.value,
                    sets = setsState.value.toIntOrNull() ?: 0,
                    exercises = exercisesState.value,
                    restTimeInSec = restTimeState.value.toIntOrNull() ?: 0
                )

                // Call the callback to insert/update the exercise group
                onWorkoutComponentUpsert(newExerciseGroup)

                // Clear form fields
                groupNameState.value = ""
                setsState.value = ""
                restTimeState.value = ""
                exercisesState.value = listOf()
            },
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp)
        ) {
            if (workoutComponent == null) Text("Insert Exercise Group") else Text("Edit Exercise Group")
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
