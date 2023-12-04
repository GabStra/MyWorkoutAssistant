package com.gabstra.myworkoutassistant

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.sets.Set

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ExerciseForm(
    onExerciseUpsert: (Set) -> Unit,
    onCancel: () -> Unit,
    set: Set? = null // Add exercise parameter with default value null
) {
    // Mutable state for form fields
    val nameState = remember { mutableStateOf(set?.name ?: "") }
    val repsState = remember { mutableStateOf(set?.reps?.toString() ?: "") }
    val weightState = remember { mutableStateOf(set?.weight?.toString() ?: "") }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        // Exercise name field
        OutlinedTextField(
            value = nameState.value,
            onValueChange = { nameState.value = it },
            label = { Text("Exercise Name") },
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp)
        )

        // Reps field
        OutlinedTextField(
            value = repsState.value,
            onValueChange = { repsState.value = it.filter { char -> char.isDigit() } },
            label = { Text("Reps") },
            keyboardOptions = KeyboardOptions.Default.copy(keyboardType = KeyboardType.Number),
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp)
        )

        // Weight field
        OutlinedTextField(
            value = weightState.value,
            onValueChange = { weightState.value = it.filter { char -> char.isDigit() || char == '.' } },
            label = { Text("Weight (kg)") },
            keyboardOptions = KeyboardOptions.Default.copy(keyboardType = KeyboardType.Number),
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp)
        )

        // Submit button
        Button(
            onClick = {
                val newSet = Set(
                    name = nameState.value,
                    reps = repsState.value.toIntOrNull() ?: 0,
                    weight = weightState.value.toFloatOrNull()
                )

                // Call the callback to insert/update the exercise
                onExerciseUpsert(newSet)

                // Clear form fields
                nameState.value = ""
                repsState.value = ""
                weightState.value = ""
            },
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp)
        ) {
            if (set == null) Text("Insert Exercise") else Text("Edit Exercise")
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
