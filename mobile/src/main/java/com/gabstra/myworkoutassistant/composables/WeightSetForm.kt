package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.utils.CalibrationHelper
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.util.UUID

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WeightSetForm(
    onSetUpsert: (Set) -> Unit,
    onCancel: () -> Unit,
    weightSet: WeightSet? = null,
    equipment: WeightLoadedEquipment,
    exercise: Exercise
) {
    val repsState = remember { mutableStateOf(weightSet?.reps?.toString() ?: "") }
    val weightState = remember { mutableStateOf(weightSet?.weight?.toString() ?: "0") }

    var possibleCombinations by remember { mutableStateOf<kotlin.collections.Set<Pair<Double, String>>>(emptySet()) }

    LaunchedEffect(Unit) {
        withContext(Dispatchers.IO) {
            possibleCombinations = equipment.getWeightsCombinationsWithLabels()
        }
    }

    val filterState = remember { mutableStateOf("") }

    val filteredCombinations = remember(filterState.value, possibleCombinations) {
        if (filterState.value.isEmpty()) {
            possibleCombinations
        } else {
            possibleCombinations.filter { (_, label) ->
                label.contains(filterState.value, ignoreCase = true)
            }
        }
    }

    val expandedWeights = remember { mutableStateOf(false) }
    val isCalibrationExercise = exercise.requiresLoadCalibration &&
        CalibrationHelper.supportsCalibrationForExercise(exercise)
    val shouldLockWeightSelection = (weightSet?.subCategory in setOf(
        SetSubCategory.CalibrationPendingSet,
        SetSubCategory.CalibrationSet
    )) || (isCalibrationExercise && (weightSet == null || weightSet.subCategory == SetSubCategory.WorkSet))
    val selectedWeight = weightState.value.toDoubleOrNull() ?: 0.0
    val weightLabel = if (equipment is Barbell) "Total Weight (KG)" else "Weight (KG)"

    Column(
        modifier = Modifier.fillMaxWidth(),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp)
        ) {
            Text(text = "Equipment: ${equipment.name}", style = MaterialTheme.typography.bodyMedium)
        }

        if (possibleCombinations.isNotEmpty()) {
            Box {
                Box {
                    OutlinedTextField(
                        value = equipment.formatWeight(selectedWeight),
                        readOnly = true,
                        onValueChange = {},
                        label = { Text(weightLabel) },
                        enabled = !shouldLockWeightSelection,
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(8.dp)
                            .then(if (shouldLockWeightSelection) Modifier.alpha(0.6f) else Modifier)
                    )
                    if (!shouldLockWeightSelection) {
                        Box(
                            modifier = Modifier
                                .matchParentSize()
                                .clickable { expandedWeights.value = true }
                        )
                    }
                }
            }

            if (shouldLockWeightSelection) {
                Text(
                    text = "This exercise is waiting to be calibrated.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 8.dp, vertical = 4.dp)
                )
            }

            if (!shouldLockWeightSelection) {
                EquipmentWeightCalculationInfo(
                    equipment = equipment,
                    totalWeight = selectedWeight
                )
            }

            if (expandedWeights.value) {
                val sortedFilteredCombinations = filteredCombinations
                    .toList()
                    .sortedBy { it.first }

                WeightPickerDialog(
                    combinations = sortedFilteredCombinations,
                    filter = filterState.value,
                    selectedWeight = selectedWeight,
                    onFilterChange = { input -> filterState.value = input },
                    onDismissRequest = { expandedWeights.value = false },
                    onSelect = { selectedWeight ->
                        weightState.value = selectedWeight.toString()
                    }
                )
            }
        } else {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp),
                contentAlignment = Alignment.Center
            ) {
                CircularProgressIndicator(
                    modifier = Modifier.width(32.dp),
                    color = MaterialTheme.colorScheme.primary,
                    trackColor = MediumDarkGray
                )
            }
        }

        OutlinedTextField(
            value = repsState.value,
            onValueChange = { input ->
                if (input.isEmpty() || input.all { it.isDigit() }) {
                    repsState.value = input
                }
            },
            label = { Text("Repetitions") },
            keyboardOptions = KeyboardOptions.Default.copy(keyboardType = KeyboardType.Number),
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp)
        )
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp),
            horizontalArrangement = Arrangement.spacedBy(Spacing.md),
            verticalAlignment = Alignment.CenterVertically
        ) {
            FormSecondaryButton(
                text = "Cancel",
                onClick = onCancel,
                modifier = Modifier.weight(1f)
            )

            FormPrimaryButton(
                text = "Save",
                onClick = {
                    val reps = repsState.value.toIntOrNull() ?: 0
                    val weight = weightState.value.toDoubleOrNull() ?: 0.0
                    val newWeightSet = WeightSet(
                        id = weightSet?.id ?: UUID.randomUUID(),
                        reps = if (reps >= 0) reps else 0,
                        weight = if (shouldLockWeightSelection) {
                            0.0
                        } else if (weight >= 0.0) {
                            weight
                        } else {
                            0.0
                        },
                        subCategory = weightSet?.subCategory ?: if (
                            exercise.requiresLoadCalibration &&
                            CalibrationHelper.supportsCalibrationForExercise(exercise)
                        ) {
                            SetSubCategory.CalibrationPendingSet
                        } else {
                            SetSubCategory.WorkSet
                        }
                    )

                    onSetUpsert(newWeightSet)
                },
                modifier = Modifier.weight(1f)
            )
        }
    }
}
