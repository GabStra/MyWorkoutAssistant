package com.gabstra.myworkoutassistant.screens

import android.app.TimePickerDialog
import android.widget.TimePicker
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable

import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.formatSecondsToMinutesSeconds
import com.gabstra.myworkoutassistant.shared.workoutcomponents.ExerciseGroup
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent



@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ExerciseGroupForm(
    onWorkoutComponentUpsert: (WorkoutComponent) -> Unit,
    onCancel: () -> Unit,
    exerciseGroup: ExerciseGroup? = null
) {
    // Mutable state for form fields
    val groupNameState = remember { mutableStateOf(exerciseGroup?.name ?: "") }
    val restTimeState = remember { mutableStateOf(exerciseGroup?.restTimeInSec?.toString() ?: "0") }
    val skipWorkoutRest = remember { mutableStateOf(exerciseGroup?.skipWorkoutRest ?: false) }

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
                label = { Text("Rest Time Between Exercises (in seconds)") },
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
                val newExerciseGroup = ExerciseGroup(
                    id  = exerciseGroup?.id ?: java.util.UUID.randomUUID(),
                    name = groupNameState.value,
                    restTimeInSec = if (restTimeInSec >= 0) restTimeInSec else 0,
                    skipWorkoutRest = skipWorkoutRest.value,
                    enabled = exerciseGroup?.enabled ?: true,
                    workoutComponents = exerciseGroup?.workoutComponents ?: listOf()
                )

                // Call the callback to insert/update the exercise group
                onWorkoutComponentUpsert(newExerciseGroup)
            },
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp)
        ) {
            if (exerciseGroup == null) Text("Insert Exercise Group") else Text("Edit Exercise Group")
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
