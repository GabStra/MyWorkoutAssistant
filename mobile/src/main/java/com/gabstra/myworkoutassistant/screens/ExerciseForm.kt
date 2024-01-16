package com.gabstra.myworkoutassistant.screens

import android.app.TimePickerDialog
import android.widget.TimePicker
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.formatSecondsToMinutesSeconds
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ExerciseForm(
    onExerciseUpsert: (Exercise) -> Unit,
    onCancel: () -> Unit,
    exercise: Exercise? = null // Add exercise parameter with default value null
) {
    // Mutable state for form fields
    val nameState = remember { mutableStateOf(exercise?.name ?: "") }
    val restTimeState = remember { mutableStateOf(exercise?.restTimeInSec?.toString() ?: "0") }
    val skipWorkoutRest = remember { mutableStateOf(exercise?.skipWorkoutRest ?: false) }

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
                .padding(8.dp),
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
                        restTimeState.value = input
                    }
                },
                label = { Text("Rest Time Between Sets (in seconds)") },
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
                checked = skipWorkoutRest.value,
                onCheckedChange = { skipWorkoutRest.value = it },
            )
            Text(text = "Skip workout rest")
        }

        // Submit button
        Button(
            onClick = {
                val restTimeInSec = restTimeState.value.toIntOrNull() ?: 0
                val newExercise = Exercise(
                    id = exercise?.id ?: java.util.UUID.randomUUID(),
                    name = nameState.value,
                    restTimeInSec = if (restTimeInSec >= 0) restTimeInSec else 0,
                    skipWorkoutRest = skipWorkoutRest.value,
                    enabled = exercise?.enabled ?: true,
                    sets = exercise?.sets ?: listOf()
                )

                // Call the callback to insert/update the exercise
                onExerciseUpsert(newExercise)

            },
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp)
        ) {
            if (exercise == null) Text("Insert Exercise") else Text("Edit Exercise")
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
