package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.clickable
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
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
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
import com.gabstra.myworkoutassistant.composables.ZoomableMuscleHeatMap
import com.gabstra.myworkoutassistant.composables.CustomTimePicker
import com.gabstra.myworkoutassistant.composables.AppPrimaryButton
import com.gabstra.myworkoutassistant.composables.AppSecondaryButton
import com.gabstra.myworkoutassistant.composables.CollapsibleSection
import com.gabstra.myworkoutassistant.composables.FormSectionTitle
import com.gabstra.myworkoutassistant.composables.LoadingOverlay
import com.gabstra.myworkoutassistant.composables.MinMaxStepperRow
import com.gabstra.myworkoutassistant.composables.StandardFilterDropdown
import com.gabstra.myworkoutassistant.composables.StandardFilterDropdownItem
import com.gabstra.myworkoutassistant.composables.rememberDebouncedSavingVisible
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.composables.TimeConverter
import com.gabstra.myworkoutassistant.round
import com.gabstra.myworkoutassistant.shared.ExerciseCategory
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.MuscleGroup
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.zoneRanges
import com.gabstra.myworkoutassistant.verticalColumnScrollbar
import java.util.Locale
import java.util.UUID
import kotlin.math.roundToInt

private fun ExerciseType.toReadableString(): String {
    return name.replace('_', ' ')
        .lowercase(Locale.ROOT)
        .replaceFirstChar { if (it.isLowerCase()) it.titlecase(Locale.ROOT) else it.toString() }
}

private fun getExerciseTypeDescriptions(): List<String> {
    return ExerciseType.values().map { it.toReadableString() }
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
    val exerciseTypeItems = remember(exerciseTypeDescriptions) {
        ExerciseType.values().zip(exerciseTypeDescriptions).map { (type, label) ->
            StandardFilterDropdownItem(
                value = type,
                label = label
            )
        }
    }

    val minLoadPercent = rememberSaveable { mutableFloatStateOf(exercise?.minLoadPercent?.toFloat() ?: 65f) }
    val maxLoadPercent = rememberSaveable { mutableFloatStateOf(exercise?.maxLoadPercent?.toFloat() ?: 85f) }
    val minReps = rememberSaveable { mutableFloatStateOf(exercise?.minReps?.toFloat() ?: 6f) }
    val maxReps = rememberSaveable { mutableFloatStateOf(exercise?.maxReps?.toFloat() ?: 12f) }

    val generateWarmupSets = rememberSaveable { mutableStateOf(exercise?.generateWarmUpSets ?: false) }
    val selectedExerciseCategory = rememberSaveable { mutableStateOf(exercise?.exerciseCategory) }
    val progressionMode = rememberSaveable { mutableStateOf(exercise?.progressionMode ?: ProgressionMode.OFF) }
    val keepScreenOn = rememberSaveable { mutableStateOf(exercise?.keepScreenOn ?: false) }
    val showCountDownTimer = rememberSaveable { mutableStateOf(exercise?.showCountDownTimer ?: false) }
    val requiresLoadCalibration = rememberSaveable { mutableStateOf(exercise?.requiresLoadCalibration ?: false) }

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

    val heartRateZoneItems = remember(heartRateZones) {
        heartRateZones.mapIndexed { index, label ->
            StandardFilterDropdownItem(value = index, label = label)
        }
    }
    val showCustomTargetZone = selectedTargetZone.value == -1

    val selectedEquipmentId = rememberSaveable { 
        mutableStateOf<UUID?>(
            exercise?.equipmentId ?: (if (exercise?.exerciseType == ExerciseType.WEIGHT) viewModel.GENERIC_ID else null)
        )
    }
    val equipmentItems: List<StandardFilterDropdownItem<UUID?>> = remember(equipments) {
        listOf(StandardFilterDropdownItem<UUID?>(value = null, label = "None")) +
            equipments.map { equipment ->
                StandardFilterDropdownItem(value = equipment.id, label = equipment.name)
            }
    }
    val exerciseCategoryOptions: List<StandardFilterDropdownItem<ExerciseCategory?>> = remember {
        listOf(
            StandardFilterDropdownItem<ExerciseCategory?>(null, "Not set"),
            StandardFilterDropdownItem(
                ExerciseCategory.HEAVY_COMPOUND,
                "Heavy compound (squat, deadlift, bench, OHP, rows)"
            ),
            StandardFilterDropdownItem(
                ExerciseCategory.MODERATE_COMPOUND,
                "Moderate compound (lunges, pull-ups, machine presses)"
            ),
            StandardFilterDropdownItem(
                ExerciseCategory.ISOLATION,
                "Isolation (curls, lateral raises, calf raises)"
            )
        )
    }
    val progressionModeOptions: List<StandardFilterDropdownItem<ProgressionMode>> = remember {
        listOf(
            StandardFilterDropdownItem(ProgressionMode.OFF, "Off"),
            StandardFilterDropdownItem(ProgressionMode.DOUBLE_PROGRESSION, "Double progression"),
            StandardFilterDropdownItem(ProgressionMode.AUTO_REGULATION, "Auto-regulation")
        )
    }

    // Validate equipment ID exists whenever equipments list changes
    LaunchedEffect(equipments, exercise?.id) {
        val currentEquipmentId = selectedEquipmentId.value
        if (currentEquipmentId != null) {
            val equipmentExists = equipments.any { it.id == currentEquipmentId }
            if (!equipmentExists) {
                // Equipment was deleted, reset to appropriate default
                selectedEquipmentId.value = if (selectedExerciseType.value == ExerciseType.WEIGHT) {
                    viewModel.GENERIC_ID
                } else {
                    null
                }
            }
        }
    }

    val selectedMuscleGroups = rememberSaveable { 
        mutableStateOf(exercise?.muscleGroups ?: emptySet<MuscleGroup>())
    }
    val selectedSecondaryMuscleGroups = rememberSaveable {
        mutableStateOf(exercise?.secondaryMuscleGroups ?: emptySet<MuscleGroup>())
    }
    var isSelectingSecondary by rememberSaveable { mutableStateOf(false) }
    var resetMuscleMapTrigger by remember { mutableStateOf(0) }

    var expandedWarmupProgression by rememberSaveable { mutableStateOf(false) }
    var expandedCalibration by rememberSaveable { mutableStateOf(false) }
    var expandedHistoryNotes by rememberSaveable { mutableStateOf(false) }
    var expandedEquipment by rememberSaveable { mutableStateOf(false) }
    var expandedTargetMuscles by rememberSaveable { mutableStateOf(false) }

    val scrollState = rememberScrollState()

    val outlineColor = MaterialTheme.colorScheme.outlineVariant

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
                .padding(vertical = Spacing.sm, horizontal = Spacing.lg)
                .verticalColumnScrollbar(scrollState)
                .verticalScroll(scrollState),
        ) {
            // ----- Essentials -----
            FormSectionTitle(text = "Essentials")
            StyledCard(modifier = Modifier.fillMaxWidth()) {
                Column(
                    modifier = Modifier.padding(Spacing.md),
                    verticalArrangement = Arrangement.spacedBy(Spacing.sm)
                ) {
                    OutlinedTextField(
                        value = nameState.value,
                        onValueChange = { nameState.value = it },
                        label = { Text("Exercise name", style = MaterialTheme.typography.labelLarge) },
                        modifier = Modifier.fillMaxWidth()
                    )
                    if (exercise == null) {
                        StandardFilterDropdown(
                            label = "Exercise type",
                            selectedText = selectedExerciseType.value.toReadableString(),
                            items = exerciseTypeItems,
                            onItemSelected = { type ->
                                selectedExerciseType.value = type
                                selectedEquipmentId.value =
                                    if (type == ExerciseType.WEIGHT) viewModel.GENERIC_ID else null
                            },
                            modifier = Modifier.fillMaxWidth(),
                            isItemSelected = { it == selectedExerciseType.value }
                        )
                    }
                }
            }

            if (nameState.value.isNotBlank()) {
                Spacer(Modifier.height(Spacing.lg))

                FormSectionTitle(text = "Training setup")
                // ----- Display -----
                Column(
                    modifier = Modifier.fillMaxWidth().padding(Spacing.md),
                    verticalArrangement = Arrangement.spacedBy(0.dp)
                ) {
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
                    if (selectedExerciseType.value == ExerciseType.COUNTDOWN || selectedExerciseType.value == ExerciseType.COUNTUP) {
                        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
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
                    }
                }

                Spacer(Modifier.height(Spacing.md))

                // ----- Equipment -----
                if (selectedExerciseType.value == ExerciseType.BODY_WEIGHT || selectedExerciseType.value == ExerciseType.WEIGHT) {
                    val selectedEquipmentName = remember(equipmentItems, selectedEquipmentId.value) {
                        equipmentItems.firstOrNull { it.value == selectedEquipmentId.value }?.label ?: "None"
                    }
                    val equipmentSummary = remember(selectedEquipmentName, selectedAccessoryIds.value, accessories) {
                        val accCount = selectedAccessoryIds.value.size
                        if (accCount == 0) "Equipment: $selectedEquipmentName"
                        else "Equipment: $selectedEquipmentName, Accessories: $accCount"
                    }
                    CollapsibleSection(
                        title = "Equipment",
                        summary = equipmentSummary,
                        expanded = expandedEquipment,
                        onToggle = { expandedEquipment = !expandedEquipment }
                    ) {
                        Column(verticalArrangement = Arrangement.spacedBy(Spacing.sm)) {
                            StandardFilterDropdown<UUID?>(
                                label = "Equipment",
                                selectedText = selectedEquipmentName,
                                items = equipmentItems,
                                onItemSelected = { selectedEquipmentId.value = it },
                                modifier = Modifier.fillMaxWidth(),
                                isItemSelected = { it == selectedEquipmentId.value }
                            )
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
                                            .padding(vertical = Spacing.xs),
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
                                            modifier = Modifier.padding(start = Spacing.sm)
                                        )
                                    }
                                }
                            }
                        }
                    }
                    Spacer(Modifier.height(Spacing.md))
                }

                // ----- Target muscles -----
                val targetMusclesSummary = remember(selectedMuscleGroups.value.size, selectedSecondaryMuscleGroups.value.size) {
                    when {
                        selectedMuscleGroups.value.isEmpty() && selectedSecondaryMuscleGroups.value.isEmpty() ->
                            "No muscles selected"
                        selectedSecondaryMuscleGroups.value.isEmpty() ->
                            "Primary: ${selectedMuscleGroups.value.size}"
                        selectedMuscleGroups.value.isEmpty() ->
                            "Secondary: ${selectedSecondaryMuscleGroups.value.size}"
                        else ->
                            "Primary: ${selectedMuscleGroups.value.size}, Secondary: ${selectedSecondaryMuscleGroups.value.size}"
                    }
                }
                CollapsibleSection(
                    title = "Target muscles",
                    summary = targetMusclesSummary,
                    expanded = expandedTargetMuscles,
                    onToggle = { expandedTargetMuscles = !expandedTargetMuscles }
                ) {
                    Column(verticalArrangement = Arrangement.spacedBy(Spacing.sm)) {
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

                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.End
                        ) {
                            OutlinedButton(
                                onClick = { resetMuscleMapTrigger++ }
                            ) {
                                Text(
                                    text = "Reset zoom & center",
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = MaterialTheme.colorScheme.onSurface
                                )
                            }
                        }

                        ZoomableMuscleHeatMap(
                            selectedMuscles = selectedMuscleGroups.value,
                            selectedSecondaryMuscles = selectedSecondaryMuscleGroups.value,
                            onMuscleToggled = { muscle ->
                                if (isSelectingSecondary) {
                                    selectedMuscleGroups.value = selectedMuscleGroups.value - muscle
                                    selectedSecondaryMuscleGroups.value = if (selectedSecondaryMuscleGroups.value.contains(muscle)) {
                                        selectedSecondaryMuscleGroups.value - muscle
                                    } else {
                                        selectedSecondaryMuscleGroups.value + muscle
                                    }
                                } else {
                                    selectedSecondaryMuscleGroups.value = selectedSecondaryMuscleGroups.value - muscle
                                    selectedMuscleGroups.value = if (selectedMuscleGroups.value.contains(muscle)) {
                                        selectedMuscleGroups.value - muscle
                                    } else {
                                        selectedMuscleGroups.value + muscle
                                    }
                                }
                            },
                            onSecondaryMuscleToggled = if (isSelectingSecondary) {
                                { muscle ->
                                    selectedMuscleGroups.value = selectedMuscleGroups.value - muscle
                                    selectedSecondaryMuscleGroups.value = if (selectedSecondaryMuscleGroups.value.contains(muscle)) {
                                        selectedSecondaryMuscleGroups.value - muscle
                                    } else {
                                        selectedSecondaryMuscleGroups.value + muscle
                                    }
                                }
                            } else null,
                            resetTrigger = resetMuscleMapTrigger
                        )
                    }
                }

                Spacer(Modifier.height(Spacing.md))
                // ----- Load & reps -----
                if (selectedExerciseType.value == ExerciseType.WEIGHT ||
                    (selectedExerciseType.value == ExerciseType.BODY_WEIGHT && selectedEquipmentId.value != null)
                ) {
                    StyledCard(modifier = Modifier.fillMaxWidth()) {
                        Column(
                            modifier = Modifier.padding(Spacing.md),
                            verticalArrangement = Arrangement.spacedBy(Spacing.sm)
                        ) {
                            Text(
                                text = "Target load range (${minLoadPercent.floatValue.toInt()}% – ${maxLoadPercent.floatValue.toInt()}%)",
                                style = MaterialTheme.typography.titleMedium,
                            )
                            MinMaxStepperRow(
                                minValue = minLoadPercent.floatValue.toInt(),
                                maxValue = maxLoadPercent.floatValue.toInt(),
                                onMinChange = { minLoadPercent.floatValue = it.toFloat() },
                                onMaxChange = { maxLoadPercent.floatValue = it.toFloat() },
                                minBound = 0,
                                maxBound = 100,
                                step = 5
                            )

                            Text(
                                text = "Target reps range (${minReps.floatValue.toInt()} – ${maxReps.floatValue.toInt()})",
                                style = MaterialTheme.typography.titleMedium,
                            )
                            MinMaxStepperRow(
                                minValue = minReps.floatValue.toInt(),
                                maxValue = maxReps.floatValue.toInt(),
                                onMinChange = { minReps.floatValue = it.toFloat() },
                                onMaxChange = { maxReps.floatValue = it.toFloat() },
                                minBound = 1,
                                maxBound = 50,
                                step = 1
                            )

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
                            }
                        }
                    }
                    Spacer(Modifier.height(Spacing.md))
                }

            if (selectedExerciseType.value == ExerciseType.BODY_WEIGHT || selectedExerciseType.value == ExerciseType.WEIGHT) {
                // Track current intra-set rest in seconds for validation and persistence
                val intraSetRestSeconds = TimeConverter.hmsToTotalSeconds(hours, minutes, seconds)

                // ----- Warm-up & progression -----
                val warmupProgressionSummary = remember(
                    generateWarmupSets.value,
                    selectedExerciseCategory.value,
                    progressionMode.value,
                    exerciseCategoryOptions
                ) {
                    val catLabel = exerciseCategoryOptions.firstOrNull { it.value == selectedExerciseCategory.value }?.label ?: "Not set"
                    val progLabel = progressionModeOptions.firstOrNull { it.value == progressionMode.value }?.label ?: "Off"
                    "Warm-up: ${if (generateWarmupSets.value) "On" else "Off"}, Category: $catLabel, Progression: $progLabel"
                }
                CollapsibleSection(
                    title = "Warm-up & progression",
                    summary = warmupProgressionSummary,
                    expanded = expandedWarmupProgression,
                    onToggle = { expandedWarmupProgression = !expandedWarmupProgression }
                ) {
                    Column(verticalArrangement = Arrangement.spacedBy(Spacing.sm)) {
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

                        val selectedExerciseCategoryLabel =
                            remember(exerciseCategoryOptions, selectedExerciseCategory.value) {
                                exerciseCategoryOptions.firstOrNull {
                                    it.value == selectedExerciseCategory.value
                                }?.label ?: "Not set"
                            }
                        StandardFilterDropdown<ExerciseCategory?>(
                            label = "Exercise category",
                            selectedText = selectedExerciseCategoryLabel,
                            items = exerciseCategoryOptions,
                            onItemSelected = { selectedExerciseCategory.value = it },
                            modifier = Modifier.fillMaxWidth(),
                            isItemSelected = { it == selectedExerciseCategory.value }
                        )

                        val selectedProgressionModeLabel =
                            remember(progressionModeOptions, progressionMode.value) {
                                progressionModeOptions.firstOrNull { it.value == progressionMode.value }?.label ?: "Off"
                            }
                        StandardFilterDropdown<ProgressionMode>(
                            label = "Progression mode",
                            selectedText = selectedProgressionModeLabel,
                            items = progressionModeOptions,
                            onItemSelected = { mode ->
                                progressionMode.value = mode
                                if (mode != ProgressionMode.OFF) {
                                    requiresLoadCalibration.value = false
                                }
                            },
                            modifier = Modifier.fillMaxWidth(),
                            isItemSelected = { it == progressionMode.value }
                        )

                        if (progressionMode.value != ProgressionMode.OFF) {
                            Text(
                                text = "Default load increase: ${(loadJumpDefaultPctState.floatValue * 100).round(2)}%",
                                style = MaterialTheme.typography.bodyLarge
                            )
                            Slider(
                                value = loadJumpDefaultPctState.floatValue,
                                onValueChange = { loadJumpDefaultPctState.floatValue = it.coerceIn(0f, 0.10f) },
                                valueRange = 0f..0.10f
                            )

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
                    }
                }

                Spacer(Modifier.height(Spacing.lg))

                // ----- Unilateral -----
                Column(
                    modifier = Modifier.fillMaxWidth().padding(Spacing.md),
                    verticalArrangement = Arrangement.spacedBy(Spacing.sm)
                ) {
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

                    if (isUnilateral.value) {
                        Text("Rest between sides", style = MaterialTheme.typography.titleMedium)
                        CustomTimePicker(
                            initialHour = hours,
                            initialMinute = minutes,
                            initialSecond = seconds,
                            onTimeChange = { h, m, s -> hms.value = Triple(h, m, s) }
                        )

                        if (intraSetRestSeconds == 0) {
                            Text(
                                text = "Set a non-zero rest between sides for unilateral exercises.",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.error
                            )
                        }
                    }
                }

                Spacer(Modifier.height(Spacing.md))
            } else {
                // ----- Heart rate (cardio) -----
                val selectedHeartRateZoneIndex = when (selectedTargetZone.value) {
                    null -> 0
                    -1 -> 5
                    else -> selectedTargetZone.value!! + 1 // 1..4 -> Zone 2..5
                }
                StyledCard(modifier = Modifier.fillMaxWidth()) {
                    Column(
                        modifier = Modifier.padding(Spacing.md),
                        verticalArrangement = Arrangement.spacedBy(Spacing.sm)
                    ) {
                        StandardFilterDropdown(
                            label = "Target heart-rate zone",
                            selectedText = heartRateZones[selectedHeartRateZoneIndex],
                            items = heartRateZoneItems,
                            onItemSelected = { index ->
                                when (index) {
                                    0 -> { // None
                                        selectedLowerBoundMaxHRPercent.value = null
                                        selectedUpperBoundMaxHRPercent.value = null
                                        selectedTargetZone.value = null
                                    }
                                    in 1..4 -> { // Zone 2..5
                                        val (lower, upper) = zoneRanges[index + 1]
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
                            },
                            modifier = Modifier.fillMaxWidth(),
                            isItemSelected = { it == selectedHeartRateZoneIndex }
                        )

                        if (showCustomTargetZone) {
                            val lb = selectedLowerBoundMaxHRPercent.value ?: 50f
                            val ub = selectedUpperBoundMaxHRPercent.value ?: 60f
                            Text(
                                text = "Custom heart-rate zone (${lb.toInt()}% – ${ub.toInt()}%)",
                                style = MaterialTheme.typography.titleMedium
                            )
                            MinMaxStepperRow(
                                minValue = lb.toInt(),
                                maxValue = ub.toInt(),
                                onMinChange = { selectedLowerBoundMaxHRPercent.value = it.toFloat() },
                                onMaxChange = { selectedUpperBoundMaxHRPercent.value = it.toFloat() },
                                minBound = 1,
                                maxBound = 100,
                                step = 5
                            )
                        }
                    }
                }
                Spacer(Modifier.height(Spacing.md))
            }

                Spacer(Modifier.height(Spacing.md))
                FormSectionTitle(text = "Advanced")
                // ----- Calibration -----
                if (selectedExerciseType.value == ExerciseType.WEIGHT ||
                    (selectedExerciseType.value == ExerciseType.BODY_WEIGHT && selectedEquipmentId.value != null && selectedEquipmentId.value != viewModel.GENERIC_ID)) {
                    CollapsibleSection(
                        title = "Calibration",
                        summary = "Calibration: ${if (requiresLoadCalibration.value) "On" else "Off"}",
                        expanded = expandedCalibration,
                        onToggle = { expandedCalibration = !expandedCalibration }
                    ) {
                        ListItem(
                            colors = ListItemDefaults.colors().copy(containerColor = Color.Transparent),
                            headlineContent = {
                                Text(
                                    "Use Calibration mode",
                                    style = MaterialTheme.typography.bodyLarge
                                )
                            },
                            supportingContent = {
                                Text(
                                    "Weight will be determined by a calibration set before the first work set.",
                                    style = MaterialTheme.typography.bodySmall
                                )
                            },
                            trailingContent = {
                                Switch(
                                    checked = requiresLoadCalibration.value,
                                    onCheckedChange = {
                                        requiresLoadCalibration.value = it
                                        if (it) {
                                            progressionMode.value = ProgressionMode.OFF
                                        }
                                    }
                                )
                            }
                        )
                    }
                    Spacer(Modifier.height(Spacing.lg))
                }

                // ----- History & notes -----
                val historyNotesSummary = remember(doNotStoreHistory.value, notesState.value) {
                    val skip = if (doNotStoreHistory.value) "Skip history: On" else "Skip history: Off"
                    val notesPreview = notesState.value.trim().take(30)
                    if (notesPreview.isEmpty()) skip else "$skip, Notes: ${notesPreview}${if (notesState.value.trim().length > 30) "…" else ""}"
                }
                CollapsibleSection(
                    title = "History & notes",
                    summary = historyNotesSummary,
                    expanded = expandedHistoryNotes,
                    onToggle = { expandedHistoryNotes = !expandedHistoryNotes }
                ) {
                    Column(verticalArrangement = Arrangement.spacedBy(Spacing.sm)) {
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

                        OutlinedTextField(
                            value = notesState.value,
                            onValueChange = { notesState.value = it },
                            label = { Text("Notes", style = MaterialTheme.typography.labelLarge) },
                            modifier = Modifier.fillMaxWidth(),
                            minLines = 3,
                            singleLine = false
                        )
                    }
                }
            } // end gating: nameState.value.isNotBlank()

            if (!nameState.value.isNotBlank()) {
                Text(
                    text = "Set a name above to configure training and advanced options.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = Spacing.md)
                )
            }

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
                AppSecondaryButton(
                    text = "Cancel",
                    onClick = onCancel,
                    modifier = Modifier.weight(1f)
                )

                AppPrimaryButton(
                    text = "Save",
                    onClick = {
                        val bodyWeightPercentageValue = bodyWeightPercentage.value.toDoubleOrNull()?.round(2)
                        val supportsCalibrationForExercise =
                            selectedExerciseType.value == ExerciseType.WEIGHT ||
                                (selectedExerciseType.value == ExerciseType.BODY_WEIGHT && selectedEquipmentId.value != null)
                        val shouldUseCalibrationSubcategories =
                            requiresLoadCalibration.value && supportsCalibrationForExercise
                        fun normalizeSetSubCategory(subCategory: SetSubCategory): SetSubCategory {
                            return if (shouldUseCalibrationSubcategories) {
                                when (subCategory) {
                                    SetSubCategory.WorkSet,
                                    SetSubCategory.CalibrationSet -> SetSubCategory.CalibrationPendingSet
                                    else -> subCategory
                                }
                            } else {
                                when (subCategory) {
                                    SetSubCategory.CalibrationPendingSet,
                                    SetSubCategory.CalibrationSet -> SetSubCategory.WorkSet
                                    else -> subCategory
                                }
                            }
                        }
                        val normalizedSets = (exercise?.sets ?: emptyList()).map { set ->
                            when (set) {
                                is WeightSet -> set.copy(
                                    subCategory = normalizeSetSubCategory(set.subCategory)
                                )
                                is BodyWeightSet -> set.copy(
                                    subCategory = normalizeSetSubCategory(set.subCategory)
                                )

                                else -> set
                            }
                        }
                        val newExercise = Exercise(
                            id = exercise?.id ?: UUID.randomUUID(),
                            name = nameState.value.trim(),
                            doNotStoreHistory = doNotStoreHistory.value,
                            enabled = exercise?.enabled ?: true,
                            sets = normalizedSets,
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
                            progressionMode = if (requiresLoadCalibration.value) ProgressionMode.OFF else progressionMode.value,
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
                            requiredAccessoryEquipmentIds = selectedAccessoryIds.value,
                            requiresLoadCalibration = requiresLoadCalibration.value,
                            exerciseCategory = selectedExerciseCategory.value
                        )
                        onExerciseUpsert(newExercise)
                    },
                    enabled = canBeSaved,
                    modifier = Modifier.weight(1f)
                )
            }

            Spacer(Modifier.height(Spacing.xl))
        }
    }
    LoadingOverlay(isVisible = rememberDebouncedSavingVisible(isSaving), text = "Saving...")
    }
}


