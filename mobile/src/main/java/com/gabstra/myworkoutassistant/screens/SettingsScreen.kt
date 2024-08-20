package com.gabstra.myworkoutassistant.screens

import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import java.util.Calendar
import java.util.Date

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    onSave:(WorkoutStore) -> Unit,
    onCancel: () -> Unit,
    workoutStore: WorkoutStore
)
{
    val context = LocalContext.current

    val polarDeviceIdState = remember { mutableStateOf(workoutStore.polarDeviceId ?: "") }
    val birthDateYearState = remember { mutableStateOf(workoutStore.birthDateYear?.toString() ?: "") }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.surfaceContainerHigh) // Set the background color to black
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(16.dp),
            verticalArrangement = Arrangement.Center,
        ) {
            OutlinedTextField(
                value = polarDeviceIdState.value,
                onValueChange = { polarDeviceIdState.value = it },
                label = { Text("Polar Device ID") },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp)
            )

            OutlinedTextField(
                value = birthDateYearState.value,
                onValueChange = { input ->
                    if (input.isEmpty() || input.all { it -> it.isDigit() }) {
                        // Update the state only if the input is empty or all characters are digits
                        birthDateYearState.value = input
                    }
                },
                label = { Text("User Year of Birth") },
                keyboardOptions = KeyboardOptions.Default.copy(keyboardType = KeyboardType.Number),
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp)
            )

            Button(
                onClick = {
                    val birthDateYear = birthDateYearState.value.toIntOrNull() ?: 0

                    val currentYear = Calendar.getInstance().get(Calendar.YEAR)

                    if (birthDateYear < 1900 || birthDateYear > currentYear) {
                        Toast.makeText(context, "Invalid birth year", Toast.LENGTH_SHORT).show()
                        return@Button
                    }

                    val newWorkoutStore = workoutStore.copy(
                        polarDeviceId = polarDeviceIdState.value,
                        birthDateYear = birthDateYear
                    )
                    onSave(newWorkoutStore)
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp)
            ) {
                Text("Save Settings")
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