package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RangeSlider
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.composables.CustomTimePicker
import com.gabstra.myworkoutassistant.composables.TimeConverter
import com.gabstra.myworkoutassistant.round
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.MediumLightGray
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.zoneRanges
import com.gabstra.myworkoutassistant.verticalColumnScrollbar
import java.util.Locale
import java.util.UUID
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

// ---- Consistent spacing scale ----------------------------------------------
private object Spacing {
    val xs = 6.dp
    val sm = 8.dp
    val md = 12.dp
    val lg = 16.dp
    val xl = 24.dp
}

private fun ExerciseType.toReadableString(): String {
    return name.replace('_', ' ')
        .lowercase(Locale.ROOT)
        .replaceFirstChar { if (it.isLowerCase()) it.titlecase(Locale.ROOT) else it.toString() }
}

private fun getExerciseTypeDescriptions(): List<String> {
    return ExerciseType.values().map { it.toReadableString() }
}

private fun stringToExerciseType(value: String): ExerciseType? {
    return ExerciseType.values().firstOrNull {
        it.name.equals(value.replace(' ', '_').uppercase(Locale.ROOT), ignoreCase = true)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ExerciseForm(
    viewModel: AppViewModel,
    onExerciseUpsert: (Exercise) -> Unit,
    onCancel: () -> Unit,
    exercise: Exercise? = null,
    allowSettingDoNotStoreHistory: Boolean = true
) {
    // ----- state -----
    val nameState = rememberSaveable { mutableStateOf(exercise?.name ?: "") }
    val notesState = rememberSaveable { mutableStateOf(exercise?.notes ?: "") }
    val doNotStoreHistory = rememberSaveable {
        mutableStateOf(exercise?.doNotStoreHistory ?: !allowSettingDoNotStoreHistory)
    }

    val hms = rememberSaveable {
        mutableStateOf(TimeConverter.secondsToHms(exercise?.intraSetRestInSeconds ?: 0))
    }
    val (hours, minutes, seconds) = hms.value

    val exerciseTypeDescriptions = rememberSaveable { getExerciseTypeDescriptions() }
    val selectedExerciseType = rememberSaveable { mutableStateOf(exercise?.exerciseType ?: ExerciseType.WEIGHT) }
    var exerciseTypeExpanded by rememberSaveable { mutableStateOf(false) }

    val minLoadPercent = rememberSaveable { mutableFloatStateOf(exercise?.minLoadPercent?.toFloat() ?: 65f) }
    val maxLoadPercent = rememberSaveable { mutableFloatStateOf(exercise?.maxLoadPercent?.toFloat() ?: 85f) }
    val minReps = rememberSaveable { mutableFloatStateOf(exercise?.minReps?.toFloat() ?: 6f) }
    val maxReps = rememberSaveable { mutableFloatStateOf(exercise?.maxReps?.toFloat() ?: 12f) }

    val generateWarmupSets = rememberSaveable { mutableStateOf(exercise?.generateWarmUpSets ?: false) }
    val enableProgression = rememberSaveable { mutableStateOf(exercise?.enableProgression ?: false) }
    val keepScreenOn = rememberSaveable { mutableStateOf(exercise?.keepScreenOn ?: false) }
    val showCountDownTimer = rememberSaveable { mutableStateOf(exercise?.showCountDownTimer ?: false) }

    val bodyWeightPercentage = rememberSaveable { mutableStateOf(exercise?.bodyWeightPercentage?.toString() ?: "") }

    val equipments by viewModel.equipmentsFlowWithGeneric.collectAsState()

    val heartRateZones = listOf("None", "Zone 2", "Zone 3", "Zone 4", "Zone 5", "Custom")
    val selectedLowerBoundMaxHRPercent = rememberSaveable { mutableStateOf(exercise?.lowerBoundMaxHRPercent) }
    val selectedUpperBoundMaxHRPercent = rememberSaveable { mutableStateOf(exercise?.upperBoundMaxHRPercent) }

    val loadJumpDefaultPctState = rememberSaveable { mutableFloatStateOf(exercise?.loadJumpDefaultPct?.toFloat() ?: 0.025f) }
    val loadJumpMaxPctState = rememberSaveable { mutableFloatStateOf(exercise?.loadJumpMaxPct?.toFloat() ?: 0.1f) }
    val loadJumpOvercapUntilState = rememberSaveable { mutableIntStateOf(exercise?.loadJumpOvercapUntil ?: 2) }

    // Map HR custom/zone selection to indices used by the menu
    val selectedTargetZone = rememberSaveable(selectedLowerBoundMaxHRPercent.value, selectedUpperBoundMaxHRPercent.value) {
        mutableStateOf(
            if (selectedLowerBoundMaxHRPercent.value == null || selectedUpperBoundMaxHRPercent.value == null) {
                null
            } else {
                val index = zoneRanges.indexOfFirst {
                    it.first == selectedLowerBoundMaxHRPercent.value && it.second == selectedUpperBoundMaxHRPercent.value
                }
                if (index == -1) {
                    -1 // custom
                } else if (index <= 1) {
                    null // out-of-range/none in your table
                } else {
                    index - 1 // menu indices 1..4 (Zone 2..5)
                }
            }
        )
    }

    var hrZoneExpanded by rememberSaveable { mutableStateOf(false) }
    val showCustomTargetZone = selectedTargetZone.value == -1

    val selectedEquipmentId = rememberSaveable { mutableStateOf<UUID?>(exercise?.equipmentId ?: viewModel.GENERIC_ID) }
    var equipmentExpanded by rememberSaveable { mutableStateOf(false) }

    val scrollState = rememberScrollState()

    Scaffold(
        topBar = {
            TopAppBar(
                modifier = Modifier.drawBehind {
                    drawLine(
                        color = MediumLightGray,
                        start = Offset(0f, size.height),
                        end = Offset(size.width, size.height),
                        strokeWidth = 1.dp.toPx()
                    )
                },
                title = {
                    Text(
                        modifier = Modifier
                            .fillMaxWidth()
                            .basicMarquee(iterations = Int.MAX_VALUE),
                        text = if (exercise == null) "Insert Exercise" else "Edit Exercise",
                        textAlign = TextAlign.Center,
                        style = MaterialTheme.typography.titleLarge
                    )
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Color.Transparent),
                navigationIcon = {
                    IconButton(onClick = onCancel) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "Back"
                        )
                    }
                },
                actions = {
                    IconButton(modifier = Modifier.alpha(0f), onClick = { }) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "Back"
                        )
                    }
                }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .padding(padding)
                .padding(top = Spacing.md)
                .verticalColumnScrollbar(scrollState)
                .verticalScroll(scrollState)
                .padding(horizontal = Spacing.lg),
        ) {
            // Name
            OutlinedTextField(
                value = nameState.value,
                onValueChange = { nameState.value = it },
                label = { Text("Exercise name", style = MaterialTheme.typography.labelLarge) },
                modifier = Modifier.fillMaxWidth()
            )

            Spacer(Modifier.height(Spacing.lg))

            // Exercise type (create only)
            if (exercise == null) {
                Text(
                    text = "Exercise type",
                    style = MaterialTheme.typography.titleMedium,
                    modifier = Modifier.padding(bottom = Spacing.sm)
                )
                ExposedDropdownMenuBox(
                    expanded = exerciseTypeExpanded,
                    onExpandedChange = { exerciseTypeExpanded = it }
                ) {
                    OutlinedTextField(
                        value = selectedExerciseType.value.toReadableString(),
                        onValueChange = {},
                        readOnly = true,
                        trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = exerciseTypeExpanded) },
                        modifier = Modifier
                            .fillMaxWidth()
                            .menuAnchor()
                    )
                    ExposedDropdownMenu(
                        expanded = exerciseTypeExpanded,
                        modifier =  Modifier.background(MaterialTheme.colorScheme.background),
                        border = BorderStroke(1.dp, MediumLightGray),
                        onDismissRequest = { exerciseTypeExpanded = false }
                    ) {
                        exerciseTypeDescriptions.forEach { desc ->
                            DropdownMenuItem(
                                text = { Text(desc, style = MaterialTheme.typography.bodyLarge) },
                                onClick = {
                                    selectedExerciseType.value = stringToExerciseType(desc)!!
                                    selectedEquipmentId.value =
                                        if (selectedExerciseType.value == ExerciseType.WEIGHT) viewModel.GENERIC_ID
                                        else null
                                    exerciseTypeExpanded = false
                                }
                            )
                        }
                    }
                }
                Spacer(Modifier.height(Spacing.lg))
                HorizontalDivider(color = MediumLightGray)
            }

            // Toggles
            ListItem(
                colors = ListItemDefaults.colors().copy(containerColor = Color.Transparent),
                headlineContent = { Text("Keep screen on", style = MaterialTheme.typography.bodyLarge) },
                trailingContent = {
                    Switch(
                        checked = keepScreenOn.value,
                        onCheckedChange = { keepScreenOn.value = it }
                    )
                }
            )
            HorizontalDivider(color = MediumLightGray)

            if (selectedExerciseType.value == ExerciseType.COUNTDOWN || selectedExerciseType.value == ExerciseType.COUNTUP) {
                ListItem(
                    colors = ListItemDefaults.colors().copy(containerColor = Color.Transparent),
                    headlineContent = { Text("Show count-down timer", style = MaterialTheme.typography.bodyLarge) },
                    trailingContent = {
                        Switch(
                            checked = showCountDownTimer.value,
                            onCheckedChange = { showCountDownTimer.value = it }
                        )
                    }
                )
                HorizontalDivider(color = MediumLightGray)
            }

            if (selectedExerciseType.value == ExerciseType.BODY_WEIGHT || selectedExerciseType.value == ExerciseType.WEIGHT) {
                Spacer(Modifier.height(Spacing.lg))

                // Equipment picker
                Text(
                    text = "Equipment",
                    style = MaterialTheme.typography.titleMedium,
                    modifier = Modifier.padding(bottom = Spacing.sm)
                )
                ExposedDropdownMenuBox(
                    expanded = equipmentExpanded,
                    onExpandedChange = { equipmentExpanded = it }
                ) {
                    val selectedEquipment = equipments.find { it.id == selectedEquipmentId.value }
                    OutlinedTextField(
                        value = selectedEquipment?.name ?: "None",
                        onValueChange = {},
                        readOnly = true,
                        trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(equipmentExpanded) },
                        modifier = Modifier
                            .fillMaxWidth()
                            .menuAnchor()
                    )
                    ExposedDropdownMenu(
                        expanded = equipmentExpanded,
                        modifier =  Modifier.background(MaterialTheme.colorScheme.background),
                        border = BorderStroke(1.dp, MediumLightGray),
                        onDismissRequest = { equipmentExpanded = false }
                    ) {
                        DropdownMenuItem(
                            text = { Text("None", style = MaterialTheme.typography.bodyLarge) },
                            onClick = {
                                selectedEquipmentId.value = null
                                equipmentExpanded = false
                            }
                        )
                        equipments.forEach { equipment ->
                            DropdownMenuItem(
                                text = { Text(equipment.name, style = MaterialTheme.typography.bodyLarge) },
                                onClick = {
                                    selectedEquipmentId.value = equipment.id
                                    equipmentExpanded = false
                                }
                            )
                        }
                    }
                }

            }

            // Weight / Bodyweight sections
            if (selectedExerciseType.value == ExerciseType.WEIGHT ||
                (selectedExerciseType.value == ExerciseType.BODY_WEIGHT && selectedEquipmentId.value != null)
            ) {
                Spacer(Modifier.height(Spacing.lg))
                Text(
                    text = "Load range (${minLoadPercent.floatValue.toInt()}% – ${maxLoadPercent.floatValue.toInt()}%)",
                    style = MaterialTheme.typography.titleMedium,
                )
                RangeSlider(
                    value = minLoadPercent.floatValue..maxLoadPercent.floatValue,
                    onValueChange = { r ->
                        minLoadPercent.floatValue = r.start
                        maxLoadPercent.floatValue = r.endInclusive
                    },
                    valueRange = 0f..100f
                )

                Spacer(Modifier.height(Spacing.md))
                Text(
                    text = "Reps range (${minReps.floatValue.toInt()} – ${maxReps.floatValue.toInt()})",
                    style = MaterialTheme.typography.titleMedium,
                )
                RangeSlider(
                    value = minReps.floatValue..maxReps.floatValue,
                    onValueChange = { r ->
                        minReps.floatValue = r.start
                        maxReps.floatValue = r.endInclusive
                    },
                    valueRange = 1f..50f
                )

                Spacer(Modifier.height(Spacing.lg))
            }

            if (selectedExerciseType.value == ExerciseType.BODY_WEIGHT) {
                OutlinedTextField(
                    value = bodyWeightPercentage.value,
                    onValueChange = {
                        if (it.isEmpty() || (it.all { ch -> ch.isDigit() || ch == '.' } && !it.startsWith("."))) {
                            bodyWeightPercentage.value = it
                        }
                    },
                    label = { Text("Bodyweight %", style = MaterialTheme.typography.labelLarge) },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    modifier = Modifier.fillMaxWidth()
                )
                Spacer(Modifier.height(Spacing.lg))
            }

            if (selectedExerciseType.value == ExerciseType.BODY_WEIGHT || selectedExerciseType.value == ExerciseType.WEIGHT) {
                // Auto warmups
                ListItem(
                    colors = ListItemDefaults.colors().copy(containerColor = Color.Transparent),
                    headlineContent = { Text("Auto-generate warm-up sets", style = MaterialTheme.typography.bodyLarge) },
                    trailingContent = {
                        Switch(
                            checked = generateWarmupSets.value,
                            onCheckedChange = { generateWarmupSets.value = it }
                        )
                    }
                )
                HorizontalDivider(color = MediumLightGray)

                // Enable progression
                ListItem(
                    colors = ListItemDefaults.colors().copy(containerColor = Color.Transparent),
                    headlineContent = { Text("Enable progression", style = MaterialTheme.typography.bodyLarge) },
                    trailingContent = {
                        Switch(
                            checked = enableProgression.value,
                            onCheckedChange = { enableProgression.value = it }
                        )
                    }
                )
                HorizontalDivider(color = MediumLightGray)

                if (enableProgression.value) {
                    Spacer(Modifier.height(Spacing.lg))
                    Text(
                        text = "Default load jump: ${(loadJumpDefaultPctState.floatValue * 100).round(2)}%",
                        style = MaterialTheme.typography.bodyLarge
                    )
                    Slider(
                        value = loadJumpDefaultPctState.floatValue,
                        onValueChange = { loadJumpDefaultPctState.floatValue = it.coerceIn(0f, 0.10f) },
                        valueRange = 0f..0.10f
                    )

                    // Ensure max slider's lower bound tracks the default value
                    val maxLower = loadJumpDefaultPctState.floatValue
                    if (loadJumpMaxPctState.floatValue < maxLower) {
                        loadJumpMaxPctState.floatValue = maxLower
                    }

                    Text(
                        text = "Max load jump: ${(loadJumpMaxPctState.floatValue * 100).roundToInt()}%",
                        style = MaterialTheme.typography.bodyLarge,
                        modifier = Modifier.padding(top = Spacing.md)
                    )
                    Slider(
                        value = loadJumpMaxPctState.floatValue,
                        onValueChange = { loadJumpMaxPctState.floatValue = it.coerceIn(maxLower, 0.25f) },
                        valueRange = maxLower..0.25f
                    )

                    Text(
                        text = "Overcap reps: ${loadJumpOvercapUntilState.intValue}",
                        style = MaterialTheme.typography.bodyLarge,
                        modifier = Modifier.padding(top = Spacing.md)
                    )
                    Slider(
                        value = loadJumpOvercapUntilState.intValue.toFloat(),
                        onValueChange = { loadJumpOvercapUntilState.intValue = it.roundToInt().coerceIn(0, 5) },
                        valueRange = 0f..5f
                    )
                }

                Spacer(Modifier.height(Spacing.lg))
                Text("Intra-set rest", style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(Spacing.sm))
                CustomTimePicker(
                    initialHour = hours,
                    initialMinute = minutes,
                    initialSecond = seconds,
                    onTimeChange = { h, m, s -> hms.value = Triple(h, m, s) }
                )

                Spacer(Modifier.height(Spacing.lg))
                HorizontalDivider(color = MediumLightGray)
            } else {
                // Cardio HR target zone
                Text(
                    text = "Target HR zone",
                    style = MaterialTheme.typography.titleMedium,
                    modifier = Modifier.padding(bottom = Spacing.sm)
                )
                ExposedDropdownMenuBox(
                    expanded = hrZoneExpanded,
                    onExpandedChange = { hrZoneExpanded = it }
                ) {
                    val zoneText = when (selectedTargetZone.value) {
                        null -> heartRateZones[0]
                        -1 -> heartRateZones[5]
                        else -> heartRateZones[selectedTargetZone.value!! + 1] // 1..4 -> Zone 2..5
                    }
                    OutlinedTextField(
                        value = zoneText,
                        onValueChange = {},
                        readOnly = true,
                        trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(hrZoneExpanded) },
                        modifier = Modifier
                            .fillMaxWidth()
                            .menuAnchor()
                    )
                    ExposedDropdownMenu(
                        expanded = hrZoneExpanded,
                        modifier =  Modifier.background(MaterialTheme.colorScheme.background),
                        border = BorderStroke(1.dp, MediumLightGray),
                        onDismissRequest = { hrZoneExpanded = false }
                    ) {
                        heartRateZones.forEachIndexed { index, zoneLabel ->
                            DropdownMenuItem(
                                text = { Text(zoneLabel, style = MaterialTheme.typography.bodyLarge) },
                                onClick = {
                                    when (index) {
                                        0 -> { // None
                                            selectedLowerBoundMaxHRPercent.value = null
                                            selectedUpperBoundMaxHRPercent.value = null
                                            selectedTargetZone.value = null
                                        }
                                        in 1..4 -> { // Zone 2..5
                                            val (lower, upper) = zoneRanges[index + 1] // align with your table
                                            selectedLowerBoundMaxHRPercent.value = lower
                                            selectedUpperBoundMaxHRPercent.value = upper
                                            selectedTargetZone.value = index
                                        }
                                        5 -> { // Custom
                                            selectedLowerBoundMaxHRPercent.value = 50f
                                            selectedUpperBoundMaxHRPercent.value = 60f
                                            selectedTargetZone.value = -1
                                        }
                                    }
                                    hrZoneExpanded = false
                                }
                            )
                        }
                    }
                }

                if (showCustomTargetZone) {
                    Spacer(Modifier.height(Spacing.lg))
                    val lb = selectedLowerBoundMaxHRPercent.value ?: 50f
                    val ub = selectedUpperBoundMaxHRPercent.value ?: 60f
                    Text(
                        text = "Custom HR zone (${lb.toInt()}% – ${ub.toInt()}%)",
                        style = MaterialTheme.typography.titleMedium
                    )
                    RangeSlider(
                        value = lb..ub,
                        onValueChange = { r ->
                            selectedLowerBoundMaxHRPercent.value = max(1f, r.start.roundToInt().toFloat())
                            selectedUpperBoundMaxHRPercent.value = min(100f, r.endInclusive.roundToInt().toFloat())
                        },
                        valueRange = 1f..100f
                    )
                }
                HorizontalDivider(color = MediumLightGray)
            }

            // Do not store history
            ListItem(
                colors = ListItemDefaults.colors().copy(containerColor = Color.Transparent),
                headlineContent = { Text("Do not store history", style = MaterialTheme.typography.bodyLarge) },
                trailingContent = {
                    Switch(
                        checked = doNotStoreHistory.value,
                        onCheckedChange = { doNotStoreHistory.value = it },
                        enabled = allowSettingDoNotStoreHistory
                    )
                }
            )
            HorizontalDivider(color = MediumLightGray)

            // Notes
            Spacer(Modifier.height(Spacing.lg))
            OutlinedTextField(
                value = notesState.value,
                onValueChange = { notesState.value = it },
                label = { Text("Notes", style = MaterialTheme.typography.labelLarge) },
                modifier = Modifier.fillMaxWidth(),
                maxLines = 5,
                singleLine = false
            )

            Spacer(Modifier.height(Spacing.xl))

            val canBeSaved =
                nameState.value.isNotBlank() &&
                        (if (selectedExerciseType.value == ExerciseType.WEIGHT) selectedEquipmentId.value != null else true)

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(Spacing.md)
            ) {
                TextButton(
                    onClick = onCancel,
                    modifier = Modifier.weight(1f)
                ) { Text("Cancel", style = MaterialTheme.typography.bodyLarge) }

                Button(
                    onClick = {
                        val bodyWeightPercentageValue = bodyWeightPercentage.value.toDoubleOrNull()
                        val newExercise = Exercise(
                            id = exercise?.id ?: UUID.randomUUID(),
                            name = nameState.value.trim(),
                            doNotStoreHistory = doNotStoreHistory.value,
                            enabled = exercise?.enabled ?: true,
                            sets = exercise?.sets ?: listOf(),
                            exerciseType = selectedExerciseType.value,
                            minLoadPercent = minLoadPercent.floatValue.toDouble(),
                            maxLoadPercent = maxLoadPercent.floatValue.toDouble(),
                            minReps = minReps.floatValue.toInt(),
                            maxReps = maxReps.floatValue.toInt(),
                            notes = notesState.value.trim(),
                            lowerBoundMaxHRPercent = selectedLowerBoundMaxHRPercent.value,
                            upperBoundMaxHRPercent = selectedUpperBoundMaxHRPercent.value,
                            equipmentId = selectedEquipmentId.value,
                            bodyWeightPercentage = bodyWeightPercentageValue ?: 0.0,
                            generateWarmUpSets = generateWarmupSets.value,
                            enableProgression = enableProgression.value,
                            keepScreenOn = keepScreenOn.value,
                            showCountDownTimer = showCountDownTimer.value,
                            intraSetRestInSeconds = TimeConverter.hmsToTotalSeconds(hours, minutes, seconds),
                            loadJumpDefaultPct = loadJumpDefaultPctState.floatValue.toDouble(),
                            loadJumpMaxPct = loadJumpMaxPctState.floatValue.toDouble(),
                            loadJumpOvercapUntil = loadJumpOvercapUntilState.intValue
                        )
                        onExerciseUpsert(newExercise)
                    },
                    enabled = canBeSaved,
                    modifier = Modifier.weight(1f)
                ) {
                    Text(if (exercise == null) "Insert" else "Save", style = MaterialTheme.typography.bodyLarge)
                }
            }

            Spacer(Modifier.height(Spacing.xl))
        }
    }
}
