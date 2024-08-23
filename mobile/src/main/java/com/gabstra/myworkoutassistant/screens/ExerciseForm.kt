package com.gabstra.myworkoutassistant.screens

import android.app.TimePickerDialog
import android.widget.TimePicker
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.formatSecondsToMinutesSeconds
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.SetType
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise

fun ExerciseType.toReadableString(): String {
    return this.name.replace('_', ' ').split(' ').joinToString(" ") { it.capitalize() }
}

fun getExerciseTypeDescriptions(): List<String> {
    return ExerciseType.values().map { it.toReadableString() }
}

fun stringToExerciseType(value: String): ExerciseType? {
    return ExerciseType.values().firstOrNull {
        it.name.equals(value.replace(' ', '_').toUpperCase(), ignoreCase = true)
    }
}


@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ExerciseForm(
    onExerciseUpsert: (Exercise) -> Unit,
    onCancel: () -> Unit,
    exercise: Exercise? = null // Add exercise parameter with default value null
) {
    // Mutable state for form fields
    val nameState = remember { mutableStateOf(exercise?.name ?: "") }
    val notesState = remember { mutableStateOf(exercise?.notes ?: "") }
    val restTimeState = remember { mutableStateOf(exercise?.restTimeInSec?.toString() ?: "0") }
    val skipWorkoutRest = remember { mutableStateOf(exercise?.skipWorkoutRest ?: false) }

    val exerciseTypeDescriptions = getExerciseTypeDescriptions()
    val selectedExerciseType = remember { mutableStateOf(exercise?.exerciseType ?: ExerciseType.WEIGHT) }
    val expanded = remember { mutableStateOf(false) }

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

        if(exercise == null){
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp)
            ) {
                Text(text = "Exercise Type:")
                Box(modifier = Modifier.fillMaxWidth()) {
                    Text(
                        text = selectedExerciseType.value.name.replace('_', ' ').capitalize(),
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
                        exerciseTypeDescriptions.forEach { ExerciseDescription ->
                            DropdownMenuItem(
                                onClick = {
                                    selectedExerciseType.value = stringToExerciseType(ExerciseDescription)!!
                                    expanded.value = false
                                },
                                text = {
                                    Text(text = ExerciseDescription)
                                }
                            )
                        }
                    }
                }
            }
            Spacer(modifier = Modifier.height(10.dp))
        }

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
                        val inputValue = input.toIntOrNull()
                        if (inputValue != null && inputValue >= 3600) {
                            restTimeState.value = "3599"
                        } else {
                            restTimeState.value = input
                        }
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

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp)
                .verticalScroll(rememberScrollState())
        ) {
            TextField(
                value = notesState.value,
                onValueChange = { notesState.value = it },
                label = { Text("Notes") },
                modifier = Modifier.fillMaxWidth(),
                maxLines = 5,
                singleLine = false
            )
        }

        // Submit button
        Button(
            colors = ButtonDefaults.buttonColors(contentColor = MaterialTheme.colorScheme.background),
            onClick = {
                if (nameState.value.isBlank()) {
                    return@Button
                }

                val restTimeInSec = restTimeState.value.toIntOrNull() ?: 0
                val newExercise = Exercise(
                    id = exercise?.id ?: java.util.UUID.randomUUID(),
                    name = nameState.value.trim(),
                    restTimeInSec = if (restTimeInSec >= 0) restTimeInSec else 0,
                    skipWorkoutRest = skipWorkoutRest.value,
                    enabled = exercise?.enabled ?: true,
                    sets = exercise?.sets ?: listOf(),
                    exerciseType = selectedExerciseType.value,
                    notes = notesState.value.trim(),
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
            colors = ButtonDefaults.buttonColors(contentColor = MaterialTheme.colorScheme.background),
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
