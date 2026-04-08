package com.gabstra.myworkoutassistant.screens

import android.widget.Toast
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
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
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.AppPrimaryButton
import com.gabstra.myworkoutassistant.composables.AppPrimaryOutlinedButton
import com.gabstra.myworkoutassistant.composables.AppSecondaryButton
import com.gabstra.myworkoutassistant.composables.ContentSubtitle
import com.gabstra.myworkoutassistant.composables.FormSectionTitle
import com.gabstra.myworkoutassistant.composables.LoadingOverlay
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.composables.rememberDebouncedSavingVisible
import com.gabstra.myworkoutassistant.getHistoricalRestingHeartRateFromHealthConnect
import com.gabstra.myworkoutassistant.shared.PolarHeartRateConfig
import com.gabstra.myworkoutassistant.shared.WhoopHeartRateConfig
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.findPolarHeartRateConfig
import com.gabstra.myworkoutassistant.shared.findWhoopHeartRateConfig
import com.gabstra.myworkoutassistant.shared.getEffectiveRestingHeartRate
import com.gabstra.myworkoutassistant.shared.getMaxHeartRate
import com.gabstra.myworkoutassistant.verticalColumnScrollbarContainer
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
    liteRtModelPath: String?,
    onImportLiteRtModel: () -> Unit,
    onClearLiteRtModel: () -> Unit,
    isSaving: Boolean = false
) {
    val context = LocalContext.current
    val coroutineScope = rememberCoroutineScope()
    val defaultRestingHeartRate = getEffectiveRestingHeartRate()
    val polarConfig = remember(workoutStore.externalHeartRateConfigs) { workoutStore.findPolarHeartRateConfig() }
    val whoopConfig = remember(workoutStore.externalHeartRateConfigs) { workoutStore.findWhoopHeartRateConfig() }

    val polarDeviceIdState = remember { mutableStateOf(polarConfig?.deviceId ?: "") }
    val polarDisplayNameState = remember { mutableStateOf(polarConfig?.displayName ?: "") }
    val whoopDeviceIdState = remember { mutableStateOf(whoopConfig?.deviceId ?: "") }
    val whoopDisplayNameState = remember { mutableStateOf(whoopConfig?.displayName ?: "") }
    val birthDateYearState = remember { mutableStateOf(workoutStore.birthDateYear.toString()) }
    val weightState = remember { mutableStateOf(workoutStore.weightKg.toString()) }
    val measuredMaxHeartRateState = remember { mutableStateOf(workoutStore.measuredMaxHeartRate?.toString() ?: "") }
    val restingHeartRateState = remember {
        mutableStateOf(getEffectiveRestingHeartRate(workoutStore.restingHeartRate).toString())
    }

    var isLoadingRestingHeartRate by remember { mutableStateOf(false) }
    val currentYear = remember { Calendar.getInstance().get(Calendar.YEAR) }
    val fallbackBirthYear = birthDateYearState.value.toIntOrNull()
    val fallbackAge = fallbackBirthYear?.let { year ->
        (currentYear - year).takeIf { it in 1..120 }
    }
    val fallbackMaxHeartRate = fallbackAge?.let(::getMaxHeartRate)

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
                .verticalColumnScrollbarContainer(scrollState)
        ) {
            FormSectionTitle("Profile")
            StyledCard(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 8.dp)
            ) {
                Column(modifier = Modifier.padding(8.dp)) {
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
                            if (input.isEmpty() || (input.count { it == '.' } <= 1 && input.all { it.isDigit() || it == '.' } && !input.startsWith("."))) {
                                weightState.value = input
                            }
                        },
                        label = { Text("Weight (kg)") },
                        keyboardOptions = KeyboardOptions.Default.copy(keyboardType = KeyboardType.Decimal),
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(8.dp)
                    )
                }
            }
            Spacer(modifier = Modifier.height(Spacing.sm))
            FormSectionTitle("Heart Rate")
            StyledCard(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 8.dp)
            ) {
                Column(modifier = Modifier.padding(8.dp)) {
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
                    ContentSubtitle(
                        text = if (fallbackAge != null && fallbackMaxHeartRate != null) {
                            "If left blank, the app uses the default formula:\n211 - 0.64 × age ($fallbackAge) = $fallbackMaxHeartRate bpm"
                        } else {
                            "If left blank, the app uses the default formula:\n211 - 0.64 × age. Enter a valid birth year to preview the fallback result."
                        },
                        modifier = Modifier.padding(horizontal = 12.dp)
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

                    AppPrimaryOutlinedButton(
                        text = if (isLoadingRestingHeartRate) {
                            "Loading Resting HR..."
                        } else {
                            "Use Health Connect Resting HR"
                        },
                        onClick = {
                            if (isLoadingRestingHeartRate) {
                                return@AppPrimaryOutlinedButton
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
                                            "Resting heart rate loaded from Health Connect.",
                                            Toast.LENGTH_SHORT
                                        ).show()
                                    } else {
                                        restingHeartRateState.value = defaultRestingHeartRate.toString()
                                        Toast.makeText(
                                            context,
                                            "No resting heart rate was found in Health Connect. Using $defaultRestingHeartRate bpm instead.",
                                            Toast.LENGTH_SHORT
                                        ).show()
                                    }
                                } catch (_: Exception) {
                                    restingHeartRateState.value = defaultRestingHeartRate.toString()
                                    Toast.makeText(
                                        context,
                                        "Couldn't read your resting heart rate from Health Connect. Using $defaultRestingHeartRate bpm instead.",
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
                    )
                }
            }
            Spacer(modifier = Modifier.height(Spacing.sm))
            FormSectionTitle("External Sensors")
            StyledCard(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 8.dp)
            ) {
                Column(modifier = Modifier.padding(8.dp)) {
                    OutlinedTextField(
                        value = polarDeviceIdState.value,
                        onValueChange = { polarDeviceIdState.value = it },
                        label = { Text("Polar Device ID") },
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(8.dp)
                    )

                    OutlinedTextField(
                        value = polarDisplayNameState.value,
                        onValueChange = { polarDisplayNameState.value = it },
                        label = { Text("Polar Display Name (optional)") },
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(8.dp)
                    )

                    OutlinedTextField(
                        value = whoopDeviceIdState.value,
                        onValueChange = { whoopDeviceIdState.value = it },
                        label = { Text("WHOOP Device ID (optional)") },
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(8.dp)
                    )

                    OutlinedTextField(
                        value = whoopDisplayNameState.value,
                        onValueChange = { whoopDisplayNameState.value = it },
                        label = { Text("WHOOP Display Name (optional)") },
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(8.dp)
                    )
                }
            }
            Spacer(modifier = Modifier.height(Spacing.sm))
            FormSectionTitle("Local Insights")
            StyledCard(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 8.dp)
            ) {
                Column(modifier = Modifier.padding(8.dp)) {
                    ContentSubtitle(
                        text = "Select the local `.litertlm` model used for on-device workout insights.",
                        modifier = Modifier.padding(horizontal = 12.dp, vertical = 4.dp)
                    )
                    OutlinedTextField(
                        value = liteRtModelPath ?: "",
                        onValueChange = {},
                        readOnly = true,
                        label = { Text("LiteRT-LM model path") },
                        placeholder = { Text("No local .litertlm model selected") },
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(8.dp)
                    )

                    AppPrimaryOutlinedButton(
                        text = if (liteRtModelPath == null) {
                            "Import LiteRT-LM model"
                        } else {
                            "Replace LiteRT-LM model"
                        },
                        onClick = onImportLiteRtModel,
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(8.dp)
                    )

                    AppSecondaryButton(
                        text = "Clear LiteRT-LM model",
                        onClick = onClearLiteRtModel,
                        enabled = liteRtModelPath != null,
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(8.dp)
                    )
                }
            }

            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                AppSecondaryButton(
                    text = "Cancel",
                    onClick = onCancel,
                    enabled = !isSaving,
                    modifier = Modifier.weight(1f)
                )

                AppPrimaryButton(
                    onClick = {
                        val birthDateYear = birthDateYearState.value.toIntOrNull()
                        val currentYear = Calendar.getInstance().get(Calendar.YEAR)

                        if (birthDateYear == null || birthDateYear < 1900 || birthDateYear > currentYear) {
                            Toast.makeText(context, "Enter a valid birth year.", Toast.LENGTH_SHORT).show()
                            return@AppPrimaryButton
                        }

                        val weight = weightState.value.toDoubleOrNull()
                        if (weight == null || weight <= 0) {
                            Toast.makeText(context, "Enter a valid body weight.", Toast.LENGTH_SHORT).show()
                            return@AppPrimaryButton
                        }

                        val measuredMaxHeartRate = measuredMaxHeartRateState.value.toIntOrNull()
                        if (measuredMaxHeartRateState.value.isNotBlank() &&
                            (measuredMaxHeartRate == null || measuredMaxHeartRate !in 120..260)
                        ) {
                            Toast.makeText(context, "Enter a valid measured max heart rate.", Toast.LENGTH_SHORT).show()
                            return@AppPrimaryButton
                        }

                        val restingHeartRate = restingHeartRateState.value.toIntOrNull()
                            ?: getEffectiveRestingHeartRate()
                        if (restingHeartRate !in 30..120) {
                            Toast.makeText(context, "Enter a valid resting heart rate.", Toast.LENGTH_SHORT).show()
                            return@AppPrimaryButton
                        }

                        val externalHeartRateConfigs = buildList {
                            val polarDeviceId = polarDeviceIdState.value.trim()
                            if (polarDeviceId.isNotEmpty()) {
                                add(
                                    PolarHeartRateConfig(
                                        deviceId = polarDeviceId,
                                        displayName = polarDisplayNameState.value.trim().ifBlank { null }
                                    )
                                )
                            }

                            val whoopDeviceId = whoopDeviceIdState.value.trim().ifBlank { null }
                            val whoopDisplayName = whoopDisplayNameState.value.trim().ifBlank { null }
                            if (whoopDeviceId != null || whoopDisplayName != null) {
                                add(
                                    WhoopHeartRateConfig(
                                        deviceId = whoopDeviceId,
                                        displayName = whoopDisplayName
                                    )
                                )
                            }
                        }

                        val newWorkoutStore = workoutStore.copy(
                            externalHeartRateConfigs = externalHeartRateConfigs,
                            birthDateYear = birthDateYear,
                            weightKg = weight,
                            measuredMaxHeartRate = measuredMaxHeartRate,
                            restingHeartRate = restingHeartRate
                        )
                        onSave(newWorkoutStore)
                    },
                    text = "Save",
                    modifier = Modifier.weight(1f)
                )
            }
        }
    }

    LoadingOverlay(isVisible = rememberDebouncedSavingVisible(isSaving), text = "Saving...")
}
