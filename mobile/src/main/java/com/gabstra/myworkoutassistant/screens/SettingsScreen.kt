package com.gabstra.myworkoutassistant.screens

import android.widget.Toast
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.round
import com.gabstra.myworkoutassistant.verticalColumnScrollbar
import java.util.Calendar

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    onSave: (WorkoutStore) -> Unit,
    onCancel: () -> Unit,
    workoutStore: WorkoutStore
) {
    val context = LocalContext.current

    val polarDeviceIdState = remember { mutableStateOf(workoutStore.polarDeviceId ?: "") }
    val birthDateYearState = remember { mutableStateOf(workoutStore.birthDateYear?.toString() ?: "") }
    val weightState = remember { mutableStateOf(workoutStore.weightKg.toString()) }
    val progressionPercentageAmount = remember { mutableStateOf(workoutStore.progressionPercentageAmount) }

    Scaffold(
        topBar = {
            TopAppBar(
                modifier = Modifier.drawBehind {
                    drawLine(
                        color = MaterialTheme.colorScheme.outlineVariant,
                        start = Offset(0f, size.height),
                        end = Offset(size.width, size.height),
                        strokeWidth = 1.dp.toPx()
                    )
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Color.Transparent),
                title = {
                    Text(
                        modifier = Modifier
                            .fillMaxWidth()
                            .basicMarquee(iterations = Int.MAX_VALUE),
                        textAlign = TextAlign.Center,
                        text = "Settings",
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onCancel) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "Back"
                        )
                    }
                },
                actions = {
                    // Invisible icon to balance the title correctly
                    IconButton(modifier = Modifier.alpha(0f), onClick = { /* No-op */ }) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = null
                        )
                    }
                }
            )
        }
    ) { paddingValues ->
        val scrollState = rememberScrollState()

        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
                .verticalColumnScrollbar(scrollState)
                .verticalScroll(scrollState)
                .padding(horizontal = 15.dp)
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
                    if (input.isEmpty() || input.all { it.isDigit() }) {
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
                    // Allow a single dot for decimals, but not as the first character
                    if (input.isEmpty() || (input.count { it == '.' } <= 1 && input.all { it.isDigit() || it == '.' } && !input.startsWith("."))) {
                        weightState.value = input
                    }
                },
                label = { Text("Weight (KG)") },
                keyboardOptions = KeyboardOptions.Default.copy(keyboardType = KeyboardType.Decimal),
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp)
            )

            Text(
                text = "Progress between Sessions: ${progressionPercentageAmount.value.round(2)}%",
                style = MaterialTheme.typography.bodyMedium,
                textAlign = TextAlign.Center,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 16.dp, bottom = 8.dp)
            )

            Slider(
                value = progressionPercentageAmount.value.toFloat(),
                onValueChange = { value ->
                    progressionPercentageAmount.value = value.toDouble()
                },
                valueRange = 0f..5f,
                steps = 19, // (5 - 0) / 0.25 - 1 = 19 steps for 0.25 increments
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 8.dp)
            )

            Button(
                colors = ButtonDefaults.buttonColors(contentColor = MaterialTheme.colorScheme.background),
                onClick = {
                    val birthDateYear = birthDateYearState.value.toIntOrNull()
                    val currentYear = Calendar.getInstance().get(Calendar.YEAR)

                    if (birthDateYear == null || birthDateYear < 1900 || birthDateYear > currentYear) {
                        Toast.makeText(context, "Invalid birth year", Toast.LENGTH_SHORT).show()
                        return@Button
                    }

                    val weight = weightState.value.toDoubleOrNull()
                    if (weight == null || weight <= 0) {
                        Toast.makeText(context, "Invalid weight", Toast.LENGTH_SHORT).show()
                        return@Button
                    }

                    val newWorkoutStore = workoutStore.copy(
                        polarDeviceId = polarDeviceIdState.value.ifBlank { null },
                        birthDateYear = birthDateYear,
                        weightKg = weight,
                        progressionPercentageAmount = progressionPercentageAmount.value
                    )
                    onSave(newWorkoutStore)
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp)
            ) {
                Text("Save Settings")
            }
        }
    }
}