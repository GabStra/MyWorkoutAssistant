package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Equipment
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import java.util.UUID

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BodyWeightSetForm(
    onSetUpsert: (Set) -> Unit,
    bodyWeightSet: BodyWeightSet? = null,
    equipment: Equipment?
) {
    // Mutable state for form fields
    val repsState = remember { mutableStateOf(bodyWeightSet?.reps?.toString() ?: "") }
    val additionalWeightState =
        remember { mutableStateOf(bodyWeightSet?.additionalWeight?.toString() ?: "") }

    Column(
        modifier = Modifier
            .fillMaxWidth()
    ) {
        if (equipment != null) {
            val equipmentVolumeMultiplier = remember(equipment) {
                equipment.volumeMultiplier ?: 1.0
            }

            val possibleCombinations = remember {
                (equipment.calculatePossibleCombinations().map {
                    if (equipment is Barbell) {
                        ((it - equipment.barWeight) / equipmentVolumeMultiplier)
                    } else {
                        it / equipmentVolumeMultiplier
                    }
                } + setOf(0.0)).toList().sorted()
            }

            val expandedWeights = remember { mutableStateOf(false) }

            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp)
            ) {
                Text(text = "Equipment: ${equipment.name}")
            }

            Box(){
                Box(){
                    OutlinedTextField(
                        value = additionalWeightState.value,
                        readOnly = true,
                        onValueChange = {
                        },
                        label = { Text("Additional Weight (kg)") },
                        keyboardOptions = KeyboardOptions.Default.copy(keyboardType = KeyboardType.Number),
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(8.dp)
                    )
                    Box(
                        modifier = Modifier
                            .matchParentSize()  // This makes the Box fill its parent size
                            .clickable { expandedWeights.value = true }
                    )
                }

                DropdownMenu(
                    expanded = expandedWeights.value,
                    onDismissRequest = { expandedWeights.value = false },
                    modifier = Modifier.background(MaterialTheme.colorScheme.surfaceContainerHigh)
                ) {
                    possibleCombinations.forEach { combo ->
                        DropdownMenuItem(
                            onClick = {
                                expandedWeights.value = false
                                additionalWeightState.value = combo.toString()
                            },
                            text = {
                                Text(text = "$combo kg")
                            }
                        )
                    }
                }
            }
        }

        // Reps field
        OutlinedTextField(
            value = repsState.value,
            onValueChange = { input ->
                if (input.isEmpty() || input.all { it -> it.isDigit() }) {
                    // Update the state only if the input is empty or all characters are digits
                    repsState.value = input
                }
            },
            label = { Text("Repetitions") },
            keyboardOptions = KeyboardOptions.Default.copy(keyboardType = KeyboardType.Number),
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp)
        )

        // Submit button
        Button(
            colors = ButtonDefaults.buttonColors(contentColor = MaterialTheme.colorScheme.background),
            onClick = {
                val reps = repsState.value.toIntOrNull() ?: 0
                val additionalWeight = additionalWeightState.value.toDoubleOrNull() ?: 0.0
                val newBodyWeightSet = BodyWeightSet(
                    id = UUID.randomUUID(),
                    reps = if (reps >= 0) reps else 0,
                    additionalWeight = additionalWeight,
                )

                // Call the callback to insert/update the exercise
                onSetUpsert(newBodyWeightSet)
            },
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp)
        ) {
            if (bodyWeightSet == null) Text("Insert Body Weight Set") else Text("Edit Body Weight Set")
        }
    }
}
