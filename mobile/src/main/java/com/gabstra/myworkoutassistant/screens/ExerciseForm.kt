package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.AppDropdownMenuItem
import com.gabstra.myworkoutassistant.composables.AppMenuContent
import com.gabstra.myworkoutassistant.composables.BodyView
import com.gabstra.myworkoutassistant.composables.CustomButton
import com.gabstra.myworkoutassistant.composables.CustomTimePicker
import com.gabstra.myworkoutassistant.composables.InteractiveMuscleHeatMap
import com.gabstra.myworkoutassistant.composables.LoadingOverlay
import com.gabstra.myworkoutassistant.composables.TimeConverter
import com.gabstra.myworkoutassistant.round
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.MuscleGroup
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.zoneRanges
import com.gabstra.myworkoutassistant.verticalColumnScrollbar
import java.util.Locale
import java.util.UUID
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

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
    allowSettingDoNotStoreHistory: Boolean = true,
    isSaving: Boolean = false
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

    // Unilateral toggle: derived from intraSetRestInSeconds domain contract (> 0 means unilateral)
    val isUnilateral = rememberSaveable {
        mutableStateOf(exercise?.intraSetRestInSeconds?.let { it > 0 } ?: false)
    }

    val bodyWeightPercentage = rememberSaveable { mutableStateOf(exercise?.bodyWeightPercentage?.toString() ?: "") }

    val equipments by viewModel.equipmentsFlowWithGeneric.collectAsState()
    val accessories by viewModel.accessoryEquipmentsFlow.collectAsState()

    val selectedAccessoryIds = rememberSaveable { 
        mutableStateOf(exercise?.requiredAccessoryEquipmentIds ?: emptyList<UUID>())
    }

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

    val selectedMuscleGroups = rememberSaveable { 
        mutableStateOf(exercise?.muscleGroups ?: emptySet<MuscleGroup>())
    }
    val selectedSecondaryMuscleGroups = rememberSaveable {
        mutableStateOf(exercise?.secondaryMuscleGroups ?: emptySet<MuscleGroup>())
    }
    var currentBodyView by rememberSaveable { mutableStateOf(BodyView.FRONT) }
    var isSelectingSecondary by rememberSaveable { mutableStateOf(false) }

    val scrollState = rememberScrollState()

    val outlineColor = MaterialTheme.colorScheme.outlineVariant
    val dropdownBackground = MaterialTheme.colorScheme.surfaceVariant
    val dropdownBorderColor = MaterialTheme.colorScheme.outlineVariant

    Box(modifier = Modifier.fillMaxSize()) {
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
                title = {
                    Text(
                        modifier = Modifier
                            .fillMaxWidth()
                            .basicMarquee(iterations = Int.MAX_VALUE),
                        text = if (exercise == null) "Create exercise" else "Edit exercise",
                        textAlign = TextAlign.Center,
                        style = MaterialTheme.typography.titleLarge
                    )
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Color.Transparent,
                    navigationIconContentColor = MaterialTheme.colorScheme.onBackground,
                    actionIconContentColor = MaterialTheme.colorScheme.onBackground
                ),
                navigationIcon = {
                    IconButton(onClick = onCancel, enabled = !isSaving) {
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
                .fillMaxSize()
                .padding(padding)
                .padding(top = 10.dp)
                .padding(bottom = 10.dp)
                .verticalColumnScrollbar(scrollState)
                .verticalScroll(scrollState)
                .padding(horizontal = 15.dp),
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
                ExposedDropdownMenuBox(
                    expanded = exerciseTypeExpanded,
                    onExpandedChange = { exerciseTypeExpanded = it }
                ) {
                    OutlinedTextField(
                        value = selectedExerciseType.value.toReadableString(),
                        label = { Text("Exercise type", style = MaterialTheme.typography.labelLarge) },
                        onValueChange = {},
                        readOnly = true,
                        trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = exerciseTypeExpanded) },
                        modifier = Modifier
                            .fillMaxWidth()
                            .menuAnchor()
                    )
                    ExposedDropdownMenu(
                        expanded = exerciseTypeExpanded,
                        modifier = Modifier.background(dropdownBackground),
                        border = BorderStroke(1.dp, dropdownBorderColor),
                        onDismissRequest = { exerciseTypeExpanded = false }
                    ) {
                        AppMenuContent {
                            exerciseTypeDescriptions.forEach { desc ->
                                AppDropdownMenuItem(
                                    text = { Text(desc) },
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
                }
                Spacer(Modifier.height(Spacing.lg))
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            }

            // Toggles
            ListItem(
                colors = ListItemDefaults.colors().copy(containerColor = Color.Transparent),
                headlineContent = { Text("Keep screen awake", style = MaterialTheme.typography.bodyLarge) },
                trailingContent = {
                    Switch(
                        checked = keepScreenOn.value,
                        onCheckedChange = { keepScreenOn.value = it }
                    )
                }
            )
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

            if (selectedExerciseType.value == ExerciseType.COUNTDOWN || selectedExerciseType.value == ExerciseType.COUNTUP) {
                ListItem(
                    colors = ListItemDefaults.colors().copy(containerColor = Color.Transparent),
                    headlineContent = { Text("Show countdown timer", style = MaterialTheme.typography.bodyLarge) },
                    trailingContent = {
                        Switch(
                            checked = showCountDownTimer.value,
                            onCheckedChange = { showCountDownTimer.value = it }
                        )
                    }
                )
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
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
                        modifier = Modifier.background(dropdownBackground),
                        border = BorderStroke(1.dp, dropdownBorderColor),
                        onDismissRequest = { equipmentExpanded = false }
                    ) {
                        AppMenuContent {
                            AppDropdownMenuItem(
                                text = { Text("None") },
                                onClick = {
                                    selectedEquipmentId.value = null
                                    equipmentExpanded = false
                                }
                            )
                            equipments.forEach { equipment ->
                                AppDropdownMenuItem(
                                    text = { Text(equipment.name) },
                                    onClick = {
                                        selectedEquipmentId.value = equipment.id
                                        equipmentExpanded = false
                                    }
                                )
                            }
                        }
                    }
                }

                // Accessories selection
                Spacer(Modifier.height(Spacing.lg))
                Text(
                    text = "Accessories",
                    style = MaterialTheme.typography.titleMedium,
                    modifier = Modifier.padding(bottom = Spacing.sm)
                )
                if (accessories.isEmpty()) {
                    Text(
                        text = "No accessories available. Add accessories in the Equipment tab.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                } else {
                    accessories.forEach { accessory ->
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = 4.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Checkbox(
                                checked = selectedAccessoryIds.value.contains(accessory.id),
                                onCheckedChange = { checked ->
                                    selectedAccessoryIds.value = if (checked) {
                                        selectedAccessoryIds.value + accessory.id
                                    } else {
                                        selectedAccessoryIds.value - accessory.id
                                    }
                                }
                            )
                            Text(
                                text = accessory.name,
                                style = MaterialTheme.typography.bodyLarge,
                                modifier = Modifier.padding(start = 8.dp)
                            )
                        }
                    }
                }
            }

            // Muscle Groups Selection
            Spacer(Modifier.height(Spacing.lg))
            Text(
                text = "Target muscles",
                style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.padding(bottom = Spacing.sm)
            )
            
            // Primary/Secondary toggle buttons
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(Spacing.sm)
            ) {
                Button(
                    onClick = { isSelectingSecondary = false },
                    modifier = Modifier.weight(1f),
                    colors = androidx.compose.material3.ButtonDefaults.buttonColors(
                        containerColor = if (!isSelectingSecondary) 
                            MaterialTheme.colorScheme.primary 
                        else 
                            MaterialTheme.colorScheme.surfaceVariant
                    )
                ) {
                    Text(
                        modifier = Modifier.fillMaxWidth(),
                        text = "Primary muscles",
                        style = MaterialTheme.typography.bodyLarge,
                        textAlign = TextAlign.Center
                    )
                }
                Button(
                    onClick = { isSelectingSecondary = true },
                    modifier = Modifier.weight(1f),
                    colors = androidx.compose.material3.ButtonDefaults.buttonColors(
                        containerColor = if (isSelectingSecondary) 
                            MaterialTheme.colorScheme.primary 
                        else 
                            MaterialTheme.colorScheme.surfaceVariant
                    )
                ) {
                    Text(
                        modifier = Modifier.fillMaxWidth(),
                        text = "Secondary muscles",
                        style = MaterialTheme.typography.bodyLarge,
                        textAlign = TextAlign.Center
                    )
                }
            }
            
            Spacer(Modifier.height(Spacing.sm))
            
            // View toggle buttons
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(Spacing.sm)
            ) {
                Button(
                    onClick = { currentBodyView = BodyView.FRONT },
                    modifier = Modifier.weight(1f),
                    colors = androidx.compose.material3.ButtonDefaults.buttonColors(
                        containerColor = if (currentBodyView == BodyView.FRONT) 
                            MaterialTheme.colorScheme.primary 
                        else 
                            MaterialTheme.colorScheme.surfaceVariant
                    )
                ) {
                    Text("Front", style = MaterialTheme.typography.bodyLarge)
                }
                Button(
                    onClick = { currentBodyView = BodyView.BACK },
                    modifier = Modifier.weight(1f),
                    colors = androidx.compose.material3.ButtonDefaults.buttonColors(
                        containerColor = if (currentBodyView == BodyView.BACK) 
                            MaterialTheme.colorScheme.primary 
                        else 
                            MaterialTheme.colorScheme.surfaceVariant
                    )
                ) {
                    Text("Back", style = MaterialTheme.typography.bodyLarge)
                }
            }
            
            Spacer(Modifier.height(Spacing.md))
            
            // Interactive Muscle Heat Map
            InteractiveMuscleHeatMap(
                selectedMuscles = selectedMuscleGroups.value,
                selectedSecondaryMuscles = selectedSecondaryMuscleGroups.value,
                onMuscleToggled = { muscle ->
                    if (isSelectingSecondary) {
                        // Remove from primary if it's there
                        selectedMuscleGroups.value = selectedMuscleGroups.value - muscle
                        // Toggle in secondary
                        selectedSecondaryMuscleGroups.value = if (selectedSecondaryMuscleGroups.value.contains(muscle)) {
                            selectedSecondaryMuscleGroups.value - muscle
                        } else {
                            selectedSecondaryMuscleGroups.value + muscle
                        }
                    } else {
                        // Remove from secondary if it's there
                        selectedSecondaryMuscleGroups.value = selectedSecondaryMuscleGroups.value - muscle
                        // Toggle in primary
                        selectedMuscleGroups.value = if (selectedMuscleGroups.value.contains(muscle)) {
                            selectedMuscleGroups.value - muscle
                        } else {
                            selectedMuscleGroups.value + muscle
                        }
                    }
                },
                onSecondaryMuscleToggled = if (isSelectingSecondary) {
                    { muscle ->
                        // Remove from primary if it's there
                        selectedMuscleGroups.value = selectedMuscleGroups.value - muscle
                        // Toggle in secondary
                        selectedSecondaryMuscleGroups.value = if (selectedSecondaryMuscleGroups.value.contains(muscle)) {
                            selectedSecondaryMuscleGroups.value - muscle
                        } else {
                            selectedSecondaryMuscleGroups.value + muscle
                        }
                    }
                } else null,
                currentView = currentBodyView
            )
            
            Spacer(Modifier.height(Spacing.lg))
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

            // Weight / Bodyweight sections
            if (selectedExerciseType.value == ExerciseType.WEIGHT ||
                (selectedExerciseType.value == ExerciseType.BODY_WEIGHT && selectedEquipmentId.value != null)
            ) {
                Spacer(Modifier.height(Spacing.lg))
                Text(
                    text = "Target load range (${minLoadPercent.floatValue.toInt()}% – ${maxLoadPercent.floatValue.toInt()}%)",
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
                    text = "Target reps range (${minReps.floatValue.toInt()} – ${maxReps.floatValue.toInt()})",
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
                    label = { Text("Bodyweight load (%)", style = MaterialTheme.typography.labelLarge) },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    modifier = Modifier.fillMaxWidth()
                )
                Spacer(Modifier.height(Spacing.lg))
            }

            if (selectedExerciseType.value == ExerciseType.BODY_WEIGHT || selectedExerciseType.value == ExerciseType.WEIGHT) {
                // Track current intra-set rest in seconds for validation and persistence
                val intraSetRestSeconds = TimeConverter.hmsToTotalSeconds(hours, minutes, seconds)

                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

                // Auto warmups
                ListItem(
                    colors = ListItemDefaults.colors().copy(containerColor = Color.Transparent),
                    headlineContent = { Text("Automatically generate warm-up sets", style = MaterialTheme.typography.bodyLarge) },
                    trailingContent = {
                        Switch(
                            checked = generateWarmupSets.value,
                            onCheckedChange = { generateWarmupSets.value = it }
                        )
                    }
                )
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

                // Enable progression
                ListItem(
                    colors = ListItemDefaults.colors().copy(containerColor = Color.Transparent),
                    headlineContent = { Text("Enable double progression", style = MaterialTheme.typography.bodyLarge) },
                    trailingContent = {
                        Switch(
                            checked = enableProgression.value,
                            onCheckedChange = { enableProgression.value = it }
                        )
                    }
                )


                if (enableProgression.value) {
                    Spacer(Modifier.height(Spacing.lg))
                    Text(
                        text = "Default load increase: ${(loadJumpDefaultPctState.floatValue * 100).round(2)}%",
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
                        text = "Maximum load increase: ${(loadJumpMaxPctState.floatValue * 100).roundToInt()}%",
                        style = MaterialTheme.typography.bodyLarge,
                        modifier = Modifier.padding(top = Spacing.md)
                    )
                    Slider(
                        value = loadJumpMaxPctState.floatValue,
                        onValueChange = { loadJumpMaxPctState.floatValue = it.coerceIn(maxLower, 0.25f) },
                        valueRange = maxLower..0.25f
                    )

                    Text(
                        text = "Overcap reps threshold: ${loadJumpOvercapUntilState.intValue}",
                        style = MaterialTheme.typography.bodyLarge,
                        modifier = Modifier.padding(top = Spacing.md)
                    )
                    Slider(
                        value = loadJumpOvercapUntilState.intValue.toFloat(),
                        onValueChange = { loadJumpOvercapUntilState.intValue = it.roundToInt().coerceIn(0, 5) },
                        valueRange = 0f..5f
                    )

                }

                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

                Spacer(Modifier.height(Spacing.lg))
                // Unilateral toggle
                ListItem(
                    colors = ListItemDefaults.colors().copy(containerColor = Color.Transparent),
                    headlineContent = {
                        Text(
                            "Unilateral exercise (left/right sides)",
                            style = MaterialTheme.typography.bodyLarge
                        )
                    },
                    supportingContent = {
                        Text(
                            "Treat each set as left and right sides with rest between sides.",
                            style = MaterialTheme.typography.bodySmall
                        )
                    },
                    trailingContent = {
                        Switch(
                            checked = isUnilateral.value,
                            onCheckedChange = { isUnilateral.value = it }
                        )
                    }
                )
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

                if (isUnilateral.value) {
                    Spacer(Modifier.height(Spacing.lg))
                    Text("Rest between sides", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(Spacing.sm))
                    CustomTimePicker(
                        initialHour = hours,
                        initialMinute = minutes,
                        initialSecond = seconds,
                        onTimeChange = { h, m, s -> hms.value = Triple(h, m, s) }
                    )

                    if (intraSetRestSeconds == 0) {
                        Spacer(Modifier.height(Spacing.sm))
                        Text(
                            text = "Set a non-zero rest between sides for unilateral exercises.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error
                        )
                    }

                    Spacer(Modifier.height(Spacing.lg))

                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                }
            } else {
                // Cardio HR target zone
                Text(
                    text = "Target heart-rate zone",
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
                        modifier = Modifier.background(dropdownBackground),
                        border = BorderStroke(1.dp, dropdownBorderColor),
                        onDismissRequest = { hrZoneExpanded = false }
                    ) {
                        AppMenuContent {
                            heartRateZones.forEachIndexed { index, zoneLabel ->
                                AppDropdownMenuItem(
                                    text = { Text(zoneLabel) },
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
                }

                if (showCustomTargetZone) {
                    Spacer(Modifier.height(Spacing.lg))
                    val lb = selectedLowerBoundMaxHRPercent.value ?: 50f
                    val ub = selectedUpperBoundMaxHRPercent.value ?: 60f
                    Text(
                        text = "Custom heart-rate zone (${lb.toInt()}% – ${ub.toInt()}%)",
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
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            }

            // Do not store history
            ListItem(
                colors = ListItemDefaults.colors().copy(containerColor = Color.Transparent),
                headlineContent = { Text("Skip exercise history tracking", style = MaterialTheme.typography.bodyLarge) },
                trailingContent = {
                    Switch(
                        checked = doNotStoreHistory.value,
                        onCheckedChange = { doNotStoreHistory.value = it },
                        enabled = allowSettingDoNotStoreHistory
                    )
                }
            )
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

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

            val intraSetRestSeconds = TimeConverter.hmsToTotalSeconds(hours, minutes, seconds)
            val canBeSaved =
                nameState.value.isNotBlank() &&
                        (if (selectedExerciseType.value == ExerciseType.WEIGHT) selectedEquipmentId.value != null else true) &&
                        (!isUnilateral.value || intraSetRestSeconds > 0)

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(Spacing.md),
                verticalAlignment = Alignment.CenterVertically
            ) {
                CustomButton(
                    text = "Cancel",
                    onClick = onCancel,
                    modifier = Modifier.weight(1f)
                )

                Button(
                    onClick = {
                        val bodyWeightPercentageValue = bodyWeightPercentage.value.toDoubleOrNull()?.round(2)
                        val newExercise = Exercise(
                            id = exercise?.id ?: UUID.randomUUID(),
                            name = nameState.value.trim(),
                            doNotStoreHistory = doNotStoreHistory.value,
                            enabled = exercise?.enabled ?: true,
                            sets = exercise?.sets ?: listOf(),
                            exerciseType = selectedExerciseType.value,
                            minLoadPercent = minLoadPercent.floatValue.toDouble().round(2),
                            maxLoadPercent = maxLoadPercent.floatValue.toDouble().round(2),
                            minReps = minReps.floatValue.toInt(),
                            maxReps = maxReps.floatValue.toInt(),
                            notes = notesState.value.trim(),
                            lowerBoundMaxHRPercent = selectedLowerBoundMaxHRPercent.value?.round(2),
                            upperBoundMaxHRPercent = selectedUpperBoundMaxHRPercent.value?.round(2),
                            equipmentId = selectedEquipmentId.value,
                            bodyWeightPercentage = bodyWeightPercentageValue ?: 0.0,
                            generateWarmUpSets = generateWarmupSets.value,
                            enableProgression = enableProgression.value,
                            keepScreenOn = keepScreenOn.value,
                            showCountDownTimer = showCountDownTimer.value,
                            intraSetRestInSeconds = if (isUnilateral.value && intraSetRestSeconds > 0) {
                                intraSetRestSeconds
                            } else {
                                null
                            },
                            loadJumpDefaultPct = loadJumpDefaultPctState.floatValue.toDouble().round(2),
                            loadJumpMaxPct = loadJumpMaxPctState.floatValue.toDouble().round(2),
                            loadJumpOvercapUntil = loadJumpOvercapUntilState.intValue,
                            muscleGroups = if (selectedMuscleGroups.value.isEmpty()) null else selectedMuscleGroups.value,
                            secondaryMuscleGroups = if (selectedSecondaryMuscleGroups.value.isEmpty()) null else selectedSecondaryMuscleGroups.value,
                            requiredAccessoryEquipmentIds = selectedAccessoryIds.value
                        )
                        onExerciseUpsert(newExercise)
                    },
                    enabled = canBeSaved,
                    modifier = Modifier.weight(1f)
                ) {
                    Text(if (exercise == null) "Create" else "Save", style = MaterialTheme.typography.bodyLarge)
                }
            }

            Spacer(Modifier.height(Spacing.xl))
        }
    }
    LoadingOverlay(isVisible = isSaving, text = "Saving...")
    }
}


