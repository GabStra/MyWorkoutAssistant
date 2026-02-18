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
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.utils.CalibrationHelper
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.util.UUID

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BodyWeightSetForm(
    onSetUpsert: (Set) -> Unit,
    onCancel: () -> Unit,
    bodyWeightSet: BodyWeightSet? = null,
    equipment: WeightLoadedEquipment?,
    exercise: Exercise
) {
    val repsState = remember { mutableStateOf(bodyWeightSet?.reps?.toString() ?: "") }
    val additionalWeightState =
        remember { mutableStateOf(bodyWeightSet?.additionalWeight?.toString() ?: "0") }
    val isCalibrationExercise = exercise.requiresLoadCalibration &&
        CalibrationHelper.supportsCalibrationForExercise(exercise)
    val shouldLockAdditionalWeightSelection = (bodyWeightSet?.subCategory in setOf(
        SetSubCategory.CalibrationPendingSet,
        SetSubCategory.CalibrationSet
    )) || (isCalibrationExercise && (bodyWeightSet == null || bodyWeightSet.subCategory == SetSubCategory.WorkSet))
    Column(modifier = Modifier.fillMaxWidth()) {
        if (equipment != null) {
            var possibleCombinations by remember { mutableStateOf<kotlin.collections.Set<Pair<Double, String>>>(emptySet()) }
            var isLoadingCombinations by remember { mutableStateOf(true) }

            LaunchedEffect(Unit) {
                withContext(Dispatchers.IO) {
                    val combinationsFromEquipment = equipment.getWeightsCombinationsWithLabels().toSet()
                    val nonZeroCombinations = combinationsFromEquipment.filter { it.first != 0.0 }.toSet()
                    possibleCombinations = nonZeroCombinations + Pair(0.0, "BW")
                }
                isLoadingCombinations = false
            }
            val showCombinationsLoading = rememberMinimumLoadingVisibility(isLoadingCombinations)

            val filterState = remember { mutableStateOf("") }

            val filteredCombinations = remember(filterState.value, possibleCombinations) {
                if (filterState.value.isEmpty()) {
                    possibleCombinations.toList()
                } else {
                    possibleCombinations.filter { (_, label) ->
                        label.contains(filterState.value, ignoreCase = true)
                    }
                }
            }

            val expandedWeights = remember { mutableStateOf(false) }
            val selectedAdditionalWeight = additionalWeightState.value.toDoubleOrNull() ?: 0.0
            val additionalWeightLabel =
                if (equipment is Barbell) "Total Additional Weight (KG)" else "Additional Weight (KG)"

            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp)
            ) {
                Text(text = "Equipment: ${equipment.name}", style = MaterialTheme.typography.bodyMedium)
            }

            if (!showCombinationsLoading) {
                Box {
                    Box {
                        OutlinedTextField(
                            value = if (selectedAdditionalWeight == 0.0) {
                                "BW"
                            } else {
                                equipment.formatWeight(selectedAdditionalWeight)
                            },
                            readOnly = true,
                            onValueChange = {},
                            label = { Text(additionalWeightLabel) },
                            enabled = !shouldLockAdditionalWeightSelection,
                            keyboardOptions = KeyboardOptions.Default.copy(keyboardType = KeyboardType.Number),
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(8.dp)
                                .then(if (shouldLockAdditionalWeightSelection) Modifier.alpha(0.6f) else Modifier)
                        )
                        if (!shouldLockAdditionalWeightSelection) {
                            Box(
                                modifier = Modifier
                                    .matchParentSize()
                                    .clickable { expandedWeights.value = true }
                            )
                        }
                    }

                    if (shouldLockAdditionalWeightSelection) {
                        Text(
                            text = "This exercise is waiting to be calibrated.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 8.dp, vertical = 4.dp)
                        )
                    }

                    if (selectedAdditionalWeight > 0.0) {
                        EquipmentWeightCalculationInfo(
                            equipment = equipment,
                            totalWeight = selectedAdditionalWeight
                        )
                    }

                    if (expandedWeights.value) {
                        val sortedFilteredCombinations = filteredCombinations
                            .toList()
                            .sortedWith(compareBy<Pair<Double, String>> { it.first != 0.0 }.thenBy { it.first })

                        WeightPickerDialog(
                            combinations = sortedFilteredCombinations,
                            filter = filterState.value,
                            selectedWeight = selectedAdditionalWeight,
                            onFilterChange = { input -> filterState.value = input },
                            onDismissRequest = { expandedWeights.value = false },
                            onSelect = { selectedWeight ->
                                additionalWeightState.value = selectedWeight.toString()
                            }
                        )
                    }
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
                    var additionalWeight = additionalWeightState.value.toDoubleOrNull() ?: 0.0
                    if (equipment == null || shouldLockAdditionalWeightSelection) {
                        additionalWeight = 0.0
                    }

                    val newBodyWeightSet = BodyWeightSet(
                        id = bodyWeightSet?.id ?: UUID.randomUUID(),
                        reps = if (reps >= 0) reps else 0,
                        additionalWeight = additionalWeight,
                        subCategory = bodyWeightSet?.subCategory ?: if (
                            exercise.requiresLoadCalibration &&
                            CalibrationHelper.supportsCalibrationForExercise(exercise)
                        ) {
                            SetSubCategory.CalibrationPendingSet
                        } else {
                            SetSubCategory.WorkSet
                        }
                    )

                    onSetUpsert(newBodyWeightSet)
                },
                modifier = Modifier.weight(1f)
            )
        }
    }
}
