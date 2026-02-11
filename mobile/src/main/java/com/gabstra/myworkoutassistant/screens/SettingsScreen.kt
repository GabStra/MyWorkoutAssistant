package com.gabstra.myworkoutassistant.screens

import android.widget.Toast
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
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
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.health.connect.client.HealthConnectClient
import com.gabstra.myworkoutassistant.composables.LoadingOverlay
import com.gabstra.myworkoutassistant.composables.FormSecondaryButton
import com.gabstra.myworkoutassistant.composables.rememberDebouncedSavingVisible
import com.gabstra.myworkoutassistant.getHistoricalRestingHeartRateFromHealthConnect
import com.gabstra.myworkoutassistant.shared.getEffectiveRestingHeartRate
import com.gabstra.myworkoutassistant.shared.DisabledContentGray
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.verticalColumnScrollbar
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.util.Calendar

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    onSave: (WorkoutStore) -> Unit,
    onCancel: () -> Unit,
    workoutStore: WorkoutStore,
    healthConnectClient: HealthConnectClient,
    isSaving: Boolean = false
) {
    val context = LocalContext.current
    val coroutineScope = rememberCoroutineScope()
    val defaultRestingHeartRate = getEffectiveRestingHeartRate()

    val polarDeviceIdState = remember { mutableStateOf(workoutStore.polarDeviceId ?: "") }
    val birthDateYearState = remember { mutableStateOf(workoutStore.birthDateYear?.toString() ?: "") }
    val weightState = remember { mutableStateOf(workoutStore.weightKg.toString()) }
    val measuredMaxHeartRateState = remember { mutableStateOf(workoutStore.measuredMaxHeartRate?.toString() ?: "") }
    val restingHeartRateState = remember {
        mutableStateOf(getEffectiveRestingHeartRate(workoutStore.restingHeartRate).toString())
    }
    
    var isLoadingRestingHeartRate by remember { mutableStateOf(false) }

    suspend fun loadRestingHeartRateWithMinimumLoadingTime(): Int? {
        val startedAt = System.currentTimeMillis()
        return try {
            getHistoricalRestingHeartRateFromHealthConnect(healthConnectClient)
        } finally {
            val elapsed = System.currentTimeMillis() - startedAt
            val remaining = 1000L - elapsed
            if (remaining > 0L) {
                delay(remaining)
            }
        }
    }
    
    LaunchedEffect(Unit) {
        if (workoutStore.restingHeartRate == null) {
            isLoadingRestingHeartRate = true
            try {
                val historicalRestingHeartRate =
                    loadRestingHeartRateWithMinimumLoadingTime()
                if (historicalRestingHeartRate != null) {
                    restingHeartRateState.value = historicalRestingHeartRate.toString()
                } else {
                    restingHeartRateState.value = defaultRestingHeartRate.toString()
                }
            } catch (_: Exception) {
                restingHeartRateState.value = defaultRestingHeartRate.toString()
            } finally {
                isLoadingRestingHeartRate = false
            }
        }
    }

    val outlineColor = MaterialTheme.colorScheme.outlineVariant

    Scaffold(
        topBar = {
            TopAppBar(
                modifier = Modifier.drawBehind {
                    drawLine(
                        color = outlineColor,
                        start = Offset(0f, size.height),
                        end = Offset(size.width, size.height),
                        strokeWidth = 1.dp.toPx()
                    )
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Color.Transparent,
                    navigationIconContentColor = MaterialTheme.colorScheme.onBackground,
                    actionIconContentColor = MaterialTheme.colorScheme.onBackground
                ),
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
                    IconButton(onClick = onCancel, enabled = !isSaving) {
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
                .padding(top = 10.dp)
                .padding(bottom = 10.dp)
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

            OutlinedTextField(
                value = measuredMaxHeartRateState.value,
                onValueChange = { input ->
                    if (input.isEmpty() || input.all { it.isDigit() }) {
                        measuredMaxHeartRateState.value = input
                    }
                },
                label = { Text("Measured HR Max (optional)") },
                keyboardOptions = KeyboardOptions.Default.copy(keyboardType = KeyboardType.Number),
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp)
            )

            OutlinedTextField(
                value = restingHeartRateState.value,
                onValueChange = { input ->
                    if (input.isEmpty() || input.all { it.isDigit() }) {
                        restingHeartRateState.value = input
                    }
                },
                label = { Text("Resting HR (bpm)") },
                keyboardOptions = KeyboardOptions.Default.copy(keyboardType = KeyboardType.Number),
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp)
            )

            OutlinedButton(
                onClick = {
                    if (isLoadingRestingHeartRate) {
                        return@OutlinedButton
                    }
                    coroutineScope.launch {
                        isLoadingRestingHeartRate = true
                        try {
                            val historicalRestingHeartRate =
                                loadRestingHeartRateWithMinimumLoadingTime()
                            if (historicalRestingHeartRate != null) {
                                restingHeartRateState.value = historicalRestingHeartRate.toString()
                                Toast.makeText(
                                    context,
                                    "Resting HR loaded from Health Connect",
                                    Toast.LENGTH_SHORT
                                ).show()
                            } else {
                                restingHeartRateState.value = defaultRestingHeartRate.toString()
                                Toast.makeText(
                                    context,
                                    "No resting HR found. Using default: $defaultRestingHeartRate bpm",
                                    Toast.LENGTH_SHORT
                                ).show()
                            }
                        } catch (_: Exception) {
                            restingHeartRateState.value = defaultRestingHeartRate.toString()
                            Toast.makeText(
                                context,
                                "Unable to read resting HR. Using default: $defaultRestingHeartRate bpm",
                                Toast.LENGTH_SHORT
                            ).show()
                        } finally {
                            isLoadingRestingHeartRate = false
                        }
                    }
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp)
            ) {
                Text(
                    text = if (isLoadingRestingHeartRate) {
                        "Loading Resting HR..."
                    } else {
                        "Use Health Connect Resting HR"
                    }
                )
            }

            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                FormSecondaryButton(
                    text = "Cancel",
                    onClick = onCancel,
                    enabled = !isSaving,
                    modifier = Modifier.weight(1f)
                )

                Button(
                    colors = ButtonDefaults.buttonColors(
                        contentColor = MaterialTheme.colorScheme.background,
                        disabledContentColor = DisabledContentGray
                    ),
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

                        val measuredMaxHeartRate = measuredMaxHeartRateState.value.toIntOrNull()
                        if (measuredMaxHeartRateState.value.isNotBlank() &&
                            (measuredMaxHeartRate == null || measuredMaxHeartRate !in 120..260)
                        ) {
                            Toast.makeText(context, "Invalid measured max HR", Toast.LENGTH_SHORT).show()
                            return@Button
                        }

                        val restingHeartRate = restingHeartRateState.value.toIntOrNull()
                            ?: getEffectiveRestingHeartRate()
                        if (restingHeartRate !in 30..120) {
                            Toast.makeText(context, "Invalid resting HR", Toast.LENGTH_SHORT).show()
                            return@Button
                        }

                        val newWorkoutStore = workoutStore.copy(
                            polarDeviceId = polarDeviceIdState.value.ifBlank { null },
                            birthDateYear = birthDateYear,
                            weightKg = weight,
                            measuredMaxHeartRate = measuredMaxHeartRate,
                            restingHeartRate = restingHeartRate
                        )
                        onSave(newWorkoutStore)
                    },
                    modifier = Modifier.weight(1f)
                ) {
                    Text("Save", color = MaterialTheme.colorScheme.onPrimary)
                }
            }
        }
    }

    LoadingOverlay(isVisible = rememberDebouncedSavingVisible(isSaving), text = "Saving...")
}
