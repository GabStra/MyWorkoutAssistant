package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.zoneRanges
import com.gabstra.myworkoutassistant.verticalColumnScrollbar
import java.util.UUID
import kotlin.math.roundToInt

fun ExerciseType.toReadableString(): String {
    return this.name.replace('_', ' ').split(' ').joinToString(" ") { it.capitalize() }
}

fun getExerciseTypeDescriptions(): List<String> {
    return ExerciseType.values().map { it.toReadableString() }
}



fun stringToExerciseType(value: String): ExerciseType? {
    return ExerciseType.values().firstOrNull {
        it.name.equals(value.replace(' ', '_').toUpperCase(), ignoreCase = true)
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

    val exerciseTypeDescriptions = getExerciseTypeDescriptions()
    val selectedExerciseType = remember { mutableStateOf(exercise?.exerciseType ?: ExerciseType.WEIGHT) }


    val expandedType = remember { mutableStateOf(false) }


    // Progressive overload state
    val minLoadPercent = remember { mutableStateOf(exercise?.minLoadPercent?.toFloat()?:65f) }
    val maxLoadPercent = remember { mutableStateOf(exercise?.maxLoadPercent?.toFloat()?:85f) }
    val minReps = remember { mutableStateOf(exercise?.minReps?.toFloat()?:6f) }
    val maxReps = remember { mutableStateOf(exercise?.maxReps?.toFloat()?:12f) }

    val generateWarmupSets = remember { mutableStateOf(exercise?.generateWarmUpSets ?: false) } // Added state for generateWarmupSets

    val bodyWeightPercentage = remember { mutableStateOf(exercise?.bodyWeightPercentage?.toString() ?: "") }

    val equipments by viewModel.equipmentsFlow.collectAsState()

    val selectedEquipmentId = remember { mutableStateOf<UUID?>(exercise?.equipmentId) }
    val expandedEquipment = remember { mutableStateOf(false) }

    val scrollState = rememberScrollState()
    Scaffold(
        topBar = {
            StyledCard(whiteOverlayAlpha =.1f, isRounded = false) {
                TopAppBar(
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
                        IconButton(modifier = Modifier.alpha(0f), onClick = {}) {
                            Icon(
                                imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                                contentDescription = "Back"
                            )
                        }
                    }
                )
            }
        }
    ){
        it ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(it)
                .padding(horizontal = 5.dp)
                .verticalColumnScrollbar(scrollState)
                .verticalScroll(scrollState)
                .padding(horizontal = 10.dp),
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
                            modifier = Modifier.background(MaterialTheme.colorScheme.surfaceContainerHigh)
                        ) {
                            exerciseTypeDescriptions.forEach { ExerciseDescription ->
                                DropdownMenuItem(
                                    onClick = {
                                        selectedExerciseType.value = stringToExerciseType(ExerciseDescription)!!
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

            if(selectedExerciseType.value == ExerciseType.WEIGHT){
                Column(
                    modifier = Modifier
                        .fillMaxWidth().padding(horizontal = 8.dp)
                ) {
                    Text(
                        text = "Load Range (${minLoadPercent.value.toInt()}% - ${maxLoadPercent.value.toInt()}%)",
                        style = MaterialTheme.typography.bodyMedium,
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
                        modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp)
                    )

                    Spacer(modifier = Modifier.height(16.dp))

                    Text(
                        text = "Reps Range (${minReps.value.toInt()} - ${maxReps.value.toInt()})",
                        style = MaterialTheme.typography.bodyMedium,
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
                        modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp)
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
                        .padding(horizontal = 8.dp) // Adjusted padding
                ) {
                    Checkbox(
                        checked = generateWarmupSets.value,
                        onCheckedChange = { generateWarmupSets.value = it },
                        colors = CheckboxDefaults.colors().copy(
                            checkedCheckmarkColor = MaterialTheme.colorScheme.background
                        )
                    )
                    Text(text = "Generate Warmup Sets")
                }
            }

            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp)
            ) {
                Text(text = "Equipment:")
                Box(modifier = Modifier.fillMaxWidth()) {
                    val selectedEquipment = equipments.find { it.id == selectedEquipmentId.value }
                    Text(
                        text = selectedEquipment?.name ?: "None",
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { expandedEquipment.value = true }
                            .padding(8.dp)
                    )
                    DropdownMenu(
                        expanded = expandedEquipment.value,
                        onDismissRequest = { expandedEquipment.value = false },
                        modifier = Modifier.background(MaterialTheme.colorScheme.surfaceContainerHigh)
                    ) {
                        DropdownMenuItem(
                            onClick = {
                                selectedEquipmentId.value =null
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

            val heartRateZones = listOf("None") + listOf("Zone 1", "Zone 2", "Zone 3", "Zone 4", "Zone 5") + listOf("Custom")
            val selectedLowerBoundMaxHRPercent = remember { mutableStateOf(exercise?.lowerBoundMaxHRPercent) }
            val selectedUpperBoundMaxHRPercent = remember { mutableStateOf(exercise?.upperBoundMaxHRPercent) }

            //get the index from zoneRanges that contains both selectedLowerBoundMaxHRPercent and selectedUpperBoundMaxHRPercent
            val selectedTargetZone = remember(selectedLowerBoundMaxHRPercent.value,selectedUpperBoundMaxHRPercent.value) {
                mutableStateOf(
                    if(selectedLowerBoundMaxHRPercent.value == null || selectedUpperBoundMaxHRPercent.value == null) null
                    else zoneRanges.indexOfFirst { it.first == selectedLowerBoundMaxHRPercent.value && it.second== selectedUpperBoundMaxHRPercent.value }
                )
            }

            val expandedHeartRateZone = remember { mutableStateOf(false) }
            val showCustomTargetZone = remember (selectedTargetZone.value) { selectedTargetZone.value!=null && selectedTargetZone.value == -1 } // Show only when custom is selected

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
                            -1 -> heartRateZones[6] // Custom
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
                        modifier = Modifier.background(MaterialTheme.colorScheme.surfaceContainerHigh)
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
                                        in 1..5 -> { // Zone 1-5
                                            val (lowerBound, upperBound) = zoneRanges[index - 1] // Adjust index for zoneRanges
                                            selectedLowerBoundMaxHRPercent.value = lowerBound
                                            selectedUpperBoundMaxHRPercent.value = upperBound
                                            selectedTargetZone.value = index - 1 // Store zone index
                                        }
                                        6 -> { // Custom
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
                Column(modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp)) { // Wrap in column for better spacing
                    Text(
                        text = "Custom HR Zone (${selectedLowerBoundMaxHRPercent.value?.toInt()}% - ${selectedUpperBoundMaxHRPercent.value?.toInt()}%)",
                        style = MaterialTheme.typography.bodyMedium,
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
                        modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp)
                    )
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
                    colors =  CheckboxDefaults.colors().copy(
                        checkedCheckmarkColor =  MaterialTheme.colorScheme.background
                    )
                )
                Text(text = "Do not store history")
            }

            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp)
            ) {
                TextField(
                    value = notesState.value,
                    onValueChange = { notesState.value = it },
                    label = { Text("Notes") },
                    modifier = Modifier.fillMaxWidth(),
                    maxLines = 5,
                    singleLine = false
                )
            }

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
                        generateWarmUpSets = generateWarmupSets.value
                    )

                    onExerciseUpsert(newExercise)
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp),
                enabled = nameState.value.isNotBlank()
            ) {
                if (exercise == null) Text("Insert Exercise") else Text("Edit Exercise")
            }

            // Cancel button
            Button(
                colors = ButtonDefaults.buttonColors(contentColor = MaterialTheme.colorScheme.background),
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
}
