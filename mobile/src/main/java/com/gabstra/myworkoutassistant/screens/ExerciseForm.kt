package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
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
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RangeSlider
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
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
import com.gabstra.myworkoutassistant.composables.CustomButton
import com.gabstra.myworkoutassistant.composables.CustomTimePicker
import com.gabstra.myworkoutassistant.composables.TimeConverter
import com.gabstra.myworkoutassistant.round
import com.gabstra.myworkoutassistant.shared.DarkGray
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.MediumDarkerGray
import com.gabstra.myworkoutassistant.shared.MediumLightGray
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.zoneRanges
import com.gabstra.myworkoutassistant.verticalColumnScrollbar
import java.util.UUID
import kotlin.math.roundToInt

fun ExerciseType.toReadableString(): String {
    return this.name.replace('_', ' ').split(' ').joinToString(" ") { it.capitalize(java.util.Locale.ROOT) }
}

fun getExerciseTypeDescriptions(): List<String> {
    return ExerciseType.values().map { it.toReadableString() }
}



fun stringToExerciseType(value: String): ExerciseType? {
    return ExerciseType.values().firstOrNull {
        it.name.equals(value.replace(' ', '_').uppercase(java.util.Locale.ROOT), ignoreCase = true)
    }
}


@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ExerciseForm(
    viewModel: AppViewModel,
    onExerciseUpsert: (Exercise) -> Unit,
    onCancel: () -> Unit,
    exercise: Exercise? = null, // Add exercise parameter with default value null
    allowSettingDoNotStoreHistory: Boolean = true
) {
    // Mutable state for form fields
    val nameState = remember { mutableStateOf(exercise?.name ?: "") }
    val notesState = remember { mutableStateOf(exercise?.notes ?: "") }
    val doNotStoreHistory = remember { mutableStateOf(exercise?.doNotStoreHistory ?: !allowSettingDoNotStoreHistory) }

    val hms = remember { mutableStateOf(TimeConverter.secondsToHms(exercise?.intraSetRestInSeconds ?: 0)) }
    val (hours, minutes, seconds) = hms.value

    val exerciseTypeDescriptions = getExerciseTypeDescriptions()
    val selectedExerciseType = remember { mutableStateOf(exercise?.exerciseType ?: ExerciseType.WEIGHT) }

    val expandedType = remember { mutableStateOf(false) }

    // Progressive overload state
    val minLoadPercent = remember { mutableStateOf(exercise?.minLoadPercent?.toFloat()?:65f) }
    val maxLoadPercent = remember { mutableStateOf(exercise?.maxLoadPercent?.toFloat()?:85f) }
    val minReps = remember { mutableStateOf(exercise?.minReps?.toFloat()?:6f) }
    val maxReps = remember { mutableStateOf(exercise?.maxReps?.toFloat()?:12f) }

    val generateWarmupSets = remember { mutableStateOf(exercise?.generateWarmUpSets ?: false) } // Added state for generateWarmupSets

    val enableProgression = remember { mutableStateOf(exercise?.enableProgression ?: false) } // Added state for enableProgression
    val keepScreenOn = remember { mutableStateOf(exercise?.keepScreenOn ?: false) } // Added state for keepScreenOn
    val showCountDownTimer = remember { mutableStateOf(exercise?.showCountDownTimer ?: false) } // Added state for keepScreenOn

    val bodyWeightPercentage = remember { mutableStateOf(exercise?.bodyWeightPercentage?.toString() ?: "") }

    val equipments by viewModel.equipmentsFlowWithGeneric.collectAsState()

    val heartRateZones = listOf("None") + listOf("Zone 2", "Zone 3", "Zone 4", "Zone 5") + listOf("Custom")
    val selectedLowerBoundMaxHRPercent = remember { mutableStateOf(exercise?.lowerBoundMaxHRPercent) }
    val selectedUpperBoundMaxHRPercent = remember { mutableStateOf(exercise?.upperBoundMaxHRPercent) }

    val loadJumpDefaultPctState = remember { mutableStateOf(exercise?.loadJumpDefaultPct?.toFloat() ?: 0.025f) }
    val loadJumpMaxPctState = remember { mutableStateOf(exercise?.loadJumpMaxPct?.toFloat() ?: 0.1f) }
    val loadJumpOvercapUntilState = remember { mutableStateOf(exercise?.loadJumpOvercapUntil?.toFloat() ?: 2f) }

    //get the index from zoneRanges that contains both selectedLowerBoundMaxHRPercent and selectedUpperBoundMaxHRPercent
    val selectedTargetZone = remember(selectedLowerBoundMaxHRPercent.value,selectedUpperBoundMaxHRPercent.value) {
        mutableStateOf(
            if(selectedLowerBoundMaxHRPercent.value == null || selectedUpperBoundMaxHRPercent.value == null) null
            else {
                val index = zoneRanges.indexOfFirst { it.first == selectedLowerBoundMaxHRPercent.value && it.second== selectedUpperBoundMaxHRPercent.value }
                if(index == -1) {
                    index
                }else if(index <= 1){
                    null
                }else{
                    index - 1
                }
            }
        )
    }

    val expandedHeartRateZone = remember { mutableStateOf(false) }
    val showCustomTargetZone = remember (selectedTargetZone.value) { selectedTargetZone.value!=null && selectedTargetZone.value == -1 } // Show only when custom is selected

    val selectedEquipmentId = remember { mutableStateOf<UUID?>(exercise?.equipmentId ?: viewModel.GENERIC_ID) }
    val expandedEquipment = remember { mutableStateOf(false) }

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
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Color.Transparent),
                title = {
                    Text(
                        modifier = Modifier
                            .fillMaxWidth()
                            .basicMarquee(iterations = Int.MAX_VALUE),
                        textAlign = TextAlign.Center,
                        text = if(exercise == null) "Insert Exercise" else "Edit Exercise"
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
                    IconButton(modifier = Modifier.alpha(0f), onClick = {
                        onCancel()
                    }) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "Back"
                        )
                    }
                }
            )
        }
    ){
        it ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(it)
                .padding(top = 10.dp)
                .verticalColumnScrollbar(scrollState)
                .verticalScroll(scrollState)
                .padding(horizontal = 15.dp),
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

            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 8.dp)
            ) {
                Checkbox(
                    checked = keepScreenOn.value,
                    onCheckedChange = { keepScreenOn.value = it },
                    colors = CheckboxDefaults.colors().copy(
                        checkedCheckmarkColor = MaterialTheme.colorScheme.onPrimary,
                        uncheckedBorderColor = MaterialTheme.colorScheme.primary
                    )
                )
                Text(text = "Keep Screen On")
            }

            if(selectedExerciseType.value == ExerciseType.COUNTDOWN || selectedExerciseType.value == ExerciseType.COUNTUP){
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 8.dp)
                ) {
                    Checkbox(
                        checked = showCountDownTimer.value,
                        onCheckedChange = { showCountDownTimer.value = it },
                        colors = CheckboxDefaults.colors().copy(
                            checkedCheckmarkColor = MaterialTheme.colorScheme.onPrimary,
                            uncheckedBorderColor = MaterialTheme.colorScheme.primary
                        )
                    )
                    Text(text = "Show CountDown Timer")
                }
            }

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
                                .clickable { expandedType.value = true }
                                .padding(8.dp)
                        )
                        DropdownMenu(
                            expanded = expandedType.value,
                            onDismissRequest = { expandedType.value = false },
                            modifier = Modifier.background(MediumDarkerGray),
                            border = BorderStroke(1.dp, MediumLightGray)
                        ) {
                            exerciseTypeDescriptions.forEach { ExerciseDescription ->
                                DropdownMenuItem(
                                    onClick = {
                                        selectedExerciseType.value = stringToExerciseType(ExerciseDescription)!!

                                        if(selectedExerciseType.value == ExerciseType.WEIGHT) selectedEquipmentId.value = viewModel.GENERIC_ID
                                        else selectedEquipmentId.value = null

                                        expandedType.value = false
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

            if(selectedExerciseType.value == ExerciseType.WEIGHT || (selectedExerciseType.value == ExerciseType.BODY_WEIGHT && selectedEquipmentId.value != null)){
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 8.dp)
                ) {
                    Text(
                        text = "Load Range (${minLoadPercent.value.toInt()}% - ${maxLoadPercent.value.toInt()}%)",
                        style = MaterialTheme.typography.titleMedium,
                        modifier = Modifier.padding(bottom = 8.dp)
                    )

                    RangeSlider(
                        value = minLoadPercent.value..maxLoadPercent.value,
                        onValueChange = { range ->
                            minLoadPercent.value = range.start
                            maxLoadPercent.value = range.endInclusive
                        },
                        valueRange = 0f..100f,
                        steps = 98,
                        modifier = Modifier.fillMaxWidth()
                    )

                    Spacer(modifier = Modifier.height(16.dp))

                    Text(
                        text = "Reps Range (${minReps.value.toInt()} - ${maxReps.value.toInt()})",
                        style = MaterialTheme.typography.titleMedium,
                        modifier = Modifier.padding(bottom = 8.dp)
                    )

                    RangeSlider(
                        value = minReps.value..maxReps.value,
                        onValueChange = { range ->
                            minReps.value = range.start
                            maxReps.value = range.endInclusive
                        },
                        valueRange = 1f..50f,
                        steps = 49,
                        modifier = Modifier.fillMaxWidth()
                    )

                    Spacer(modifier = Modifier.height(16.dp)) // Added spacer
                }
            }

            if(selectedExerciseType.value == ExerciseType.BODY_WEIGHT){
                Spacer(modifier = Modifier.height(8.dp))
                OutlinedTextField(
                    value = bodyWeightPercentage.value,
                    onValueChange = {
                        if (it.isEmpty() || (it.all { it.isDigit() || it == '.' } && !it.startsWith("."))) {
                            bodyWeightPercentage.value = it
                        }
                    },
                    label = { Text("BodyWeight %") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    modifier = Modifier.fillMaxWidth()
                )
            }

            if(selectedExerciseType.value == ExerciseType.BODY_WEIGHT || selectedExerciseType.value == ExerciseType.WEIGHT){
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 8.dp)
                ) {
                    Checkbox(
                        checked = generateWarmupSets.value,
                        onCheckedChange = { generateWarmupSets.value = it },
                        colors = CheckboxDefaults.colors().copy(
                            checkedCheckmarkColor = MaterialTheme.colorScheme.onPrimary,
                            uncheckedBorderColor = MaterialTheme.colorScheme.primary
                        )
                    )
                    Text(text = "Auto-Generate Warm-up Sets")
                }

                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 8.dp)
                ) {
                    Checkbox(
                        checked = enableProgression.value,
                        onCheckedChange = { enableProgression.value = it },
                        colors = CheckboxDefaults.colors().copy(
                            checkedCheckmarkColor = MaterialTheme.colorScheme.onPrimary,
                            uncheckedBorderColor = MaterialTheme.colorScheme.primary
                        )
                    )
                    Text(text = "Enable Progression")
                }

                if (enableProgression.value) {
                    Column(modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp)) {
                        // Default Percentage Slider
                        Text(
                            text = "Default Load Jump: ${(loadJumpDefaultPctState.value * 100).round(2)}%",
                            style = MaterialTheme.typography.bodyMedium,
                            modifier = Modifier.padding(top = 16.dp)
                        )
                        Slider(
                            value = loadJumpDefaultPctState.value,
                            onValueChange = { loadJumpDefaultPctState.value = it },
                            valueRange = 0f..0.1f, // 0% to 10%
                            steps = 39 // Allows for 0.25% increments
                        )

                        // Max Percentage Slider
                        Text(
                            text = "Max Load Jump: ${(loadJumpMaxPctState.value * 100).roundToInt()}%",
                            style = MaterialTheme.typography.bodyMedium,
                            modifier = Modifier.padding(top = 8.dp)
                        )
                        val maxLoadJumpStartRange = loadJumpDefaultPctState.value
                        val maxLoadJumpEndRange = 0.25f
                        // Calculate the number of 1% steps within the dynamic range.
                        // The number of steps is the number of intervals minus one.
                        val maxLoadJumpSteps = ((maxLoadJumpEndRange - maxLoadJumpStartRange) / 0.01f).roundToInt() - 1

                        Slider(
                            value = loadJumpMaxPctState.value,
                            onValueChange = { loadJumpMaxPctState.value = it },
                            valueRange = maxLoadJumpStartRange..maxLoadJumpEndRange, // Default + 5% to 25%
                            steps = if (maxLoadJumpSteps > 0) maxLoadJumpSteps else 0 // Ensure steps is not negative
                        )

                        // Overcap Reps Slider
                        Text(
                            text = "Overcap Reps: ${loadJumpOvercapUntilState.value.toInt()}",
                            style = MaterialTheme.typography.bodyMedium,
                            modifier = Modifier.padding(top = 8.dp)
                        )
                        Slider(
                            value = loadJumpOvercapUntilState.value,
                            onValueChange = { loadJumpOvercapUntilState.value = it.roundToInt().toFloat() },
                            valueRange = 0f..5f,
                            steps = 4 // Allows for integer increments
                        )
                    }
                }

                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(8.dp),
                ) {
                    Text("Intra-Set Rest")
                    Spacer(modifier = Modifier.height(15.dp))
                    CustomTimePicker(
                        initialHour = hours,
                        initialMinute = minutes,
                        initialSecond = seconds,
                        onTimeChange = { hour, minute, second ->
                            hms.value = Triple(hour, minute, second)
                        }
                    )
                }

                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(8.dp)
                ) {
                    Text(text = "Equipment:", style = MaterialTheme.typography.titleMedium)
                    Box(modifier = Modifier.fillMaxWidth()) {
                        val selectedEquipment = equipments.find { it.id == selectedEquipmentId.value }
                        Text(
                            text = selectedEquipment?.name ?: "None",
                            style = MaterialTheme.typography.titleMedium,
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable { expandedEquipment.value = true }
                                .padding(8.dp)
                        )
                        DropdownMenu(
                            expanded = expandedEquipment.value,
                            onDismissRequest = { expandedEquipment.value = false },
                            modifier = Modifier.background(MediumDarkerGray),
                            border = BorderStroke(1.dp, MediumLightGray)
                        ) {
                            DropdownMenuItem(
                                onClick = {
                                    selectedEquipmentId.value = null
                                    expandedEquipment.value = false
                                },
                                text = {
                                    Text(text = "None")
                                }
                            )
                            equipments.forEach { equipment ->
                                DropdownMenuItem(
                                    onClick = {
                                        selectedEquipmentId.value = equipment.id
                                        expandedEquipment.value = false
                                    },
                                    text = {
                                        Text(text = equipment.name)
                                    }
                                )
                            }
                        }
                    }
                }
            }else{
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(8.dp)
                ) {
                    Text(text = "Target HR Zone:")
                    Box(modifier = Modifier.fillMaxWidth()) {
                        Text(
                            text = when(selectedTargetZone.value) {
                                null -> heartRateZones[0] // None
                                -1 -> heartRateZones[5] // Custom
                                else -> heartRateZones[selectedTargetZone.value!! + 1] // Zone 1-5 (index + 1)
                            },
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable { expandedHeartRateZone.value = true }
                                .padding(8.dp)
                        )
                        DropdownMenu(
                            expanded = expandedHeartRateZone.value,
                            onDismissRequest = { expandedHeartRateZone.value = false },
                            modifier = Modifier.background(MediumDarkerGray),
                            border = BorderStroke(1.dp, MediumLightGray)
                        ) {
                            heartRateZones.forEachIndexed { index, zone ->
                                DropdownMenuItem(
                                    onClick = {
                                        when (index) {
                                            0 -> { // None
                                                selectedLowerBoundMaxHRPercent.value = null
                                                selectedUpperBoundMaxHRPercent.value = null
                                                selectedTargetZone.value = null
                                            }
                                            in 1..4 -> { // Zone 2-5
                                                val (lowerBound, upperBound) = zoneRanges[index + 1] // Adjust index for zoneRanges
                                                selectedLowerBoundMaxHRPercent.value = lowerBound
                                                selectedUpperBoundMaxHRPercent.value = upperBound
                                                selectedTargetZone.value = index // Store zone index
                                            }
                                            5 -> { // Custom
                                                selectedLowerBoundMaxHRPercent.value = 50f // Default custom range
                                                selectedUpperBoundMaxHRPercent.value = 60f
                                                selectedTargetZone.value = -1 // Indicate custom
                                            }
                                        }
                                        expandedHeartRateZone.value = false
                                    },
                                    text = {
                                        Text(text = zone)
                                    }
                                )
                            }
                        }
                    }
                }

                if(showCustomTargetZone){
                    Column(modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 8.dp)) { // Wrap in column for better spacing
                        Text(
                            text = "Custom HR Zone (${selectedLowerBoundMaxHRPercent.value?.toInt()}% - ${selectedUpperBoundMaxHRPercent.value?.toInt()}%)",
                            style = MaterialTheme.typography.titleMedium,
                            modifier = Modifier.padding(bottom = 8.dp)
                        )
                        RangeSlider(
                            value =  selectedLowerBoundMaxHRPercent.value!!..selectedUpperBoundMaxHRPercent.value!!,
                            onValueChange = { range ->
                                selectedLowerBoundMaxHRPercent.value = range.start.roundToInt().toFloat()
                                selectedUpperBoundMaxHRPercent.value = range.endInclusive.roundToInt().toFloat()
                            },
                            valueRange = 1f..100f,
                            steps = 99,
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 8.dp)
                        )
                    }
                }
            }

            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp)
            ) {
                Checkbox(
                    checked = doNotStoreHistory.value,
                    onCheckedChange = { doNotStoreHistory.value = it },
                    enabled = allowSettingDoNotStoreHistory,
                    colors = CheckboxDefaults.colors().copy(
                        checkedCheckmarkColor = MaterialTheme.colorScheme.onPrimary,
                        uncheckedBorderColor = MaterialTheme.colorScheme.primary
                    )
                )
                Text(text = "Do not store history")
            }

            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp)
            ) {
                OutlinedTextField(
                    value = notesState.value,
                    onValueChange = { notesState.value = it },
                    label = { Text("Notes") },
                    modifier = Modifier.fillMaxWidth(),
                    maxLines = 5,
                    singleLine = false
                )
            }

            val canBeSaved = nameState.value.isNotBlank() && if(selectedExerciseType.value == ExerciseType.WEIGHT) selectedEquipmentId.value != null else true

            // Submit button
            Button(
                colors = ButtonDefaults.buttonColors(contentColor = MaterialTheme.colorScheme.background),
                onClick = {
                    val bodyWeightPercentageValue = bodyWeightPercentage.value.toDoubleOrNull()
                    val newExercise = Exercise(
                        id = exercise?.id ?: java.util.UUID.randomUUID(),
                        name = nameState.value.trim(),
                        doNotStoreHistory = doNotStoreHistory.value,
                        enabled = exercise?.enabled ?: true,
                        sets = exercise?.sets ?: listOf(),
                        exerciseType = selectedExerciseType.value,
                        minLoadPercent = minLoadPercent.value.toDouble(),
                        maxLoadPercent = maxLoadPercent.value.toDouble(),
                        minReps = minReps.value.toInt(),
                        maxReps = maxReps.value.toInt(),
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
                        loadJumpDefaultPct = loadJumpDefaultPctState.value.toDouble(),
                        loadJumpMaxPct = loadJumpMaxPctState.value.toDouble(),
                        loadJumpOvercapUntil = loadJumpOvercapUntilState.value.toInt()
                    )

                    onExerciseUpsert(newExercise)
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp),
                enabled = canBeSaved
            ) {
                if (exercise == null) Text("Insert Exercise", color = if(canBeSaved) DarkGray else Color.Unspecified) else Text("Edit Exercise", color = if(canBeSaved) DarkGray else Color.Unspecified)
            }

            CustomButton(
                text = "Cancel",
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
