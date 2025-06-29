package com.gabstra.myworkoutassistant.screens

import android.widget.Toast
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RangeSlider
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.composables.CustomOutlinedButton
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.round
import com.gabstra.myworkoutassistant.shared.LightGray
import com.gabstra.myworkoutassistant.shared.MediumGray
import com.gabstra.myworkoutassistant.shared.MediumLightGray
import java.util.Calendar

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
    val weightState = remember { mutableStateOf(workoutStore.weightKg.toString() ?: "") }

    val minWorkloadProgressionState = remember { mutableStateOf(workoutStore.workloadProgressionLowerRange) }
    val maxWorkloadProgressionState = remember { mutableStateOf(workoutStore.workloadProgressionUpperRange) }


    Box(
        modifier = Modifier
            .fillMaxSize()
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

            OutlinedTextField(
                value = weightState.value,
                onValueChange = { input ->
                    if (input.isEmpty() || (input.all { it.isDigit() || it == '.' } && !input.startsWith("."))) {
                        // Update the state only if the input is empty or all characters are digits
                        weightState.value = input
                    }
                },
                label = { Text("Weight (kg)") },
                keyboardOptions = KeyboardOptions.Default.copy(keyboardType = KeyboardType.Number),
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp)
            )

            Text(
                text = "Workload Progress Range (${minWorkloadProgressionState.value.round(2)}% - ${maxWorkloadProgressionState.value.round(2)}%)",
                style = MaterialTheme.typography.bodyMedium,
                textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth().padding(bottom = 8.dp)
            )

            RangeSlider(
                value = minWorkloadProgressionState.value.toFloat()..maxWorkloadProgressionState.value.toFloat(),
                onValueChange = { range ->
                    minWorkloadProgressionState.value = range.start.toDouble()
                    maxWorkloadProgressionState.value = range.endInclusive.toDouble()
                },
                valueRange = 0f..5f,
                steps = 19, // (5 - 0) / 0.25 - 1 = 19 steps
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 8.dp)
            )

            Button(
                colors = ButtonDefaults.buttonColors(contentColor = MaterialTheme.colorScheme.background),
                onClick = {
                    val birthDateYear = birthDateYearState.value.toIntOrNull() ?: 0

                    val currentYear = Calendar.getInstance().get(Calendar.YEAR)

                    if (birthDateYear < 1900 || birthDateYear > currentYear) {
                        Toast.makeText(context, "Invalid birth year", Toast.LENGTH_SHORT).show()
                        return@Button
                    }

                    val newWorkoutStore = workoutStore.copy(
                        polarDeviceId = polarDeviceIdState.value,
                        birthDateYear = birthDateYear,
                        weightKg = weightState.value.toDoubleOrNull() ?: 0.0,
                        workloadProgressionLowerRange = minWorkloadProgressionState.value,
                        workloadProgressionUpperRange = maxWorkloadProgressionState.value
                    )
                    onSave(newWorkoutStore)
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp)
            ) {
                Text("Save Settings", color = LightGray)
            }

            // Cancel button
            CustomOutlinedButton(
                text = "Cancel",
                color = MediumLightGray,
                onClick = {
                    onCancel()
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp)
            )
        }
    }

}