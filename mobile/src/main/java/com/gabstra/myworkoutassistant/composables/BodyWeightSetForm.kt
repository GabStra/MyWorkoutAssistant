package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.DisabledContentGray
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.verticalColumnScrollbar
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.util.UUID

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BodyWeightSetForm(
    onSetUpsert: (Set) -> Unit,
    bodyWeightSet: BodyWeightSet? = null,
    equipment: WeightLoadedEquipment?,
    exercise: Exercise
) {
    val repsState = remember { mutableStateOf(bodyWeightSet?.reps?.toString() ?: "") }
    val additionalWeightState =
        remember { mutableStateOf(bodyWeightSet?.additionalWeight?.toString() ?: "0") }

    Column(modifier = Modifier.fillMaxWidth()) {
        if (equipment != null) {
            var possibleCombinations by remember { mutableStateOf<kotlin.collections.Set<Pair<Double, String>>>(emptySet()) }

            LaunchedEffect(Unit) {
                withContext(Dispatchers.IO) {
                    val combinationsFromEquipment = equipment.getWeightsCombinationsWithLabels().toSet()
                    val nonZeroCombinations = combinationsFromEquipment.filter { it.first != 0.0 }.toSet()
                    possibleCombinations = nonZeroCombinations + Pair(0.0, "BW")
                }
            }

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
            val isCalibrationEnabled = exercise.requiresLoadCalibration
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

            if (possibleCombinations.isNotEmpty()) {
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
                            enabled = !isCalibrationEnabled,
                            keyboardOptions = KeyboardOptions.Default.copy(keyboardType = KeyboardType.Number),
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(8.dp)
                                .then(if (isCalibrationEnabled) Modifier.alpha(0.6f) else Modifier)
                        )
                        if (!isCalibrationEnabled) {
                            Box(
                                modifier = Modifier
                                    .matchParentSize()
                                    .clickable { expandedWeights.value = true }
                            )
                        }
                    }

                    val scrollState = rememberScrollState()

                    if (isCalibrationEnabled) {
                        Text(
                            text = "Additional weight will be determined by calibration set",
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

                    AppDropdownMenu(
                        expanded = expandedWeights.value,
                        onDismissRequest = { expandedWeights.value = false },
                        modifier = Modifier.fillMaxWidth(.75f)
                    ) {
                        Column(
                            modifier = Modifier.padding(horizontal = 10.dp),
                            verticalArrangement = Arrangement.spacedBy(5.dp)
                        ) {
                            Text(
                                modifier = Modifier.fillMaxWidth(),
                                text = "Available Weights",
                                style = MaterialTheme.typography.titleMedium,
                                textAlign = TextAlign.Center
                            )

                            OutlinedTextField(
                                value = filterState.value,
                                onValueChange = { input ->
                                    filterState.value = input
                                },
                                label = { Text("Filter") },
                                modifier = Modifier.fillMaxWidth()
                            )

                            Column(
                                modifier = Modifier
                                    .padding(top = 5.dp)
                                    .padding(bottom = 5.dp)
                                    .height(300.dp)
                                    .fillMaxWidth()
                                    .verticalColumnScrollbar(scrollState)
                                    .verticalScroll(scrollState)
                                    .padding(horizontal = 15.dp),
                                verticalArrangement = Arrangement.spacedBy(5.dp)
                            ) {
                                filteredCombinations
                                    .sortedWith(compareBy<Pair<Double, String>> { it.first != 0.0 }.thenBy { it.first })
                                    .forEach { (combo, label) ->
                                        StyledCard(
                                            modifier = Modifier.clickable {
                                                expandedWeights.value = false
                                                additionalWeightState.value = combo.toString()
                                            }
                                        ) {
                                            Row(
                                                modifier = Modifier
                                                    .fillMaxWidth()
                                                    .padding(5.dp),
                                                horizontalArrangement = Arrangement.Center,
                                                verticalAlignment = Alignment.CenterVertically
                                            ) {
                                                Text(text = label)
                                            }
                                        }
                                    }
                            }
                        }
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

        Button(
            colors = ButtonDefaults.buttonColors(
                contentColor = MaterialTheme.colorScheme.background,
                disabledContentColor = DisabledContentGray
            ),
            onClick = {
                val reps = repsState.value.toIntOrNull() ?: 0
                var additionalWeight = additionalWeightState.value.toDoubleOrNull() ?: 0.0
                if (equipment == null) {
                    additionalWeight = 0.0
                }

                val newBodyWeightSet = BodyWeightSet(
                    id = UUID.randomUUID(),
                    reps = if (reps >= 0) reps else 0,
                    additionalWeight = additionalWeight
                )

                onSetUpsert(newBodyWeightSet)
            },
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp)
        ) {
            if (bodyWeightSet == null) {
                Text("Save", color = MaterialTheme.colorScheme.onPrimary)
            } else {
                Text("Save", color = MaterialTheme.colorScheme.onPrimary)
            }
        }
    }
}
