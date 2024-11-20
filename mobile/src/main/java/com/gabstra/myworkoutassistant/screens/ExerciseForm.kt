package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.utils.ProgressionHelper
import com.gabstra.myworkoutassistant.shared.utils.ProgressionHelper.getParametersByExerciseType
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise

fun ExerciseType.toReadableString(): String {
    return this.name.replace('_', ' ').split(' ').joinToString(" ") { it.capitalize() }
}

fun ProgressionHelper.ExerciseCategory.toReadableString(): String {
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

fun getExerciseCategoryDescriptions(): List<String> {
    return ProgressionHelper.ExerciseCategory.values().map { it.toReadableString() }
}

fun stringToExerciseCategory(value: String): ProgressionHelper.ExerciseCategory? {
    return ProgressionHelper.ExerciseCategory.values().firstOrNull {
        it.name.equals(value.replace(' ', '_').toUpperCase(), ignoreCase = true)
    }
}



@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ExerciseForm(
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

    val exerciseCategoryDescriptions = getExerciseCategoryDescriptions()
    val selectedExerciseCategory = remember { mutableStateOf(exercise?.exerciseCategory) }

    val expandedType = remember { mutableStateOf(false) }
    val expandedCategory = remember { mutableStateOf(false) }

    // Progressive overload state
    val minLoadPercent = remember { mutableStateOf(exercise?.minLoadPercent?.toFloat()?:65f) }
    val maxLoadPercent = remember { mutableStateOf(exercise?.maxLoadPercent?.toFloat()?:85f) }
    val minReps = remember { mutableStateOf(exercise?.minReps?.toFloat()?:6f) }
    val maxReps = remember { mutableStateOf(exercise?.maxReps?.toFloat()?:12f) }
    val fatigueFactor = remember { mutableStateOf(exercise?.fatigueFactor?:0.1f) }
    val volumeIncreasePercent = remember { mutableStateOf(exercise?.volumeIncreasePercent?:5f) } // Default 5% increase

    // Update parameters when category changes
    fun updateProgressiveOverloadParameters(category: ProgressionHelper.ExerciseCategory?) {
        val parameters = category?.let { getParametersByExerciseType(it) }
        parameters?.let {
            minLoadPercent.value = it.percentLoadRange.first.toFloat()
            maxLoadPercent.value = it.percentLoadRange.second.toFloat()
            minReps.value = it.repsRange.first.toFloat()
            maxReps.value = it.repsRange.last.toFloat()
            fatigueFactor.value = it.fatigueFactor.toFloat()
            volumeIncreasePercent.value = 5f
        }
    }

    val scrollState = rememberScrollState()
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
            .verticalScroll(scrollState),
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

        if(selectedExerciseType.value == ExerciseType.WEIGHT || selectedExerciseType.value == ExerciseType.BODY_WEIGHT){
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp)
            ) {
                Text(text = "Exercise Category:")
                Box(modifier = Modifier.fillMaxWidth()) {
                    Text(
                        text = selectedExerciseCategory.value?.name?.replace('_', ' ')?.capitalize() ?: "-",
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { expandedCategory.value = true }
                            .padding(8.dp)
                    )
                    DropdownMenu(
                        expanded = expandedCategory.value,
                        onDismissRequest = { expandedCategory.value = false },
                        modifier = Modifier.background(MaterialTheme.colorScheme.surfaceContainerHigh)
                    ) {
                        exerciseCategoryDescriptions.forEach { exerciseDescription ->
                            DropdownMenuItem(
                                onClick = {
                                    val category = stringToExerciseCategory(exerciseDescription)!!
                                    selectedExerciseCategory.value = category
                                    updateProgressiveOverloadParameters(category)
                                    expandedCategory.value = false
                                },
                                text = {
                                    Text(text = exerciseDescription)
                                }
                            )
                        }
                    }
                }
            }

            // Progressive Overload Section
            if (selectedExerciseCategory.value != null) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(16.dp)
                ) {
                    Text(
                        text = "Progressive Overload Parameters",
                        style = MaterialTheme.typography.titleMedium,
                        modifier = Modifier.padding(bottom = 16.dp)
                    )

                    if(selectedExerciseType.value == ExerciseType.WEIGHT){
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
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 8.dp)
                        )

                        Spacer(modifier = Modifier.height(16.dp))
                    }

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
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 8.dp)
                    )

                    Text(
                        text = "Volume Increase per Session (${volumeIncreasePercent.value.toInt()}%)",
                        style = MaterialTheme.typography.bodyMedium,
                        modifier = Modifier.padding(bottom = 8.dp)
                    )

                    Slider(
                        value = volumeIncreasePercent.value,
                        onValueChange = { volumeIncreasePercent.value = it },
                        valueRange = 0f..20f,
                        steps = 19,
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 8.dp)
                    )

                    OutlinedButton(
                        onClick = {
                            // Reset to default values for the selected category
                            updateProgressiveOverloadParameters(selectedExerciseCategory.value)
                        },
                        modifier = Modifier
                            .align(Alignment.CenterHorizontally)
                            .padding(top = 8.dp)
                    ) {
                        Text("Reset to Defaults")
                    }
                }
            }
        }

        val heartRateZones = listOf("None") + listOf("Zone 1", "Zone 2", "Zone 3", "Zone 4", "Zone 5")
        val selectedTargetZone = remember { mutableStateOf(exercise?.targetZone) }
        val expandedHeartRateZone = remember { mutableStateOf(false) }

        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp)
        ) {
            Text(text = "Target Heart Rate Zone:")
            Box(modifier = Modifier.fillMaxWidth()) {
                Text(
                    text = when(selectedTargetZone.value) {
                        null -> heartRateZones[0]
                        else -> heartRateZones[selectedTargetZone.value!!]
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
                                selectedTargetZone.value = if(index == 0) null else index
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
                val newExercise = Exercise(
                    id = exercise?.id ?: java.util.UUID.randomUUID(),
                    name = nameState.value.trim(),
                    doNotStoreHistory = doNotStoreHistory.value,
                    enabled = exercise?.enabled ?: true,
                    sets = exercise?.sets ?: listOf(),
                    exerciseType = selectedExerciseType.value,
                    exerciseCategory = selectedExerciseCategory.value,
                    minLoadPercent = minLoadPercent.value.toDouble(),
                    maxLoadPercent = maxLoadPercent.value.toDouble(),
                    minReps = minReps.value.toInt(),
                    maxReps = maxReps.value.toInt(),
                    fatigueFactor = fatigueFactor.value,
                    volumeIncreasePercent = volumeIncreasePercent.value,
                    notes = notesState.value.trim(),
                    targetZone = selectedTargetZone.value
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
