package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.BorderStroke
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
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.ui.theme.LightGray
import com.gabstra.myworkoutassistant.ui.theme.MediumGray
import java.util.UUID

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WeightSetForm(
    onSetUpsert: (Set) -> Unit,
    weightSet: WeightSet? = null,
    equipment: Equipment
) {
    // Mutable state for form fields
    val repsState = remember { mutableStateOf(weightSet?.reps?.toString() ?: "") }
    val weightState = remember { mutableStateOf(weightSet?.weight?.toString() ?: "") }

    val equipmentVolumeMultiplier = remember(equipment) {
        equipment.volumeMultiplier ?: 1.0
    }

    val possibleCombinations = remember { equipment.calculatePossibleCombinations().map{
            if(equipment is Barbell){
                ((it - equipment.barWeight) / equipmentVolumeMultiplier)
            }else{
                it / equipmentVolumeMultiplier
            }
        }
    }


    val expandedWeights = remember { mutableStateOf(false) }

    Column(
        modifier = Modifier
            .fillMaxWidth()
    ) {

        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp)
        ) {
            Text(text = "Equipment: ${equipment.name}", style = MaterialTheme.typography.bodyMedium)
        }

        Box(){
            Box(){
                OutlinedTextField(
                    value = weightState.value,
                    readOnly = true,
                    onValueChange = {
                    },
                    label = { Text("Weight (kg)") },
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
                modifier = Modifier.background(MaterialTheme.colorScheme.surfaceContainerHigh),
                border = BorderStroke(1.dp, MediumGray)
            ) {
                possibleCombinations.forEach { combo ->
                    DropdownMenuItem(
                        onClick = {
                            expandedWeights.value = false
                            weightState.value = combo.toString()
                        },
                        text = {
                            Text(text = "$combo kg")
                        }
                    )
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
                val weight = weightState.value.toDoubleOrNull() ?: 0.0
                val newWeightSet = WeightSet(
                    id = UUID.randomUUID(),
                    reps = if (reps >= 0) reps else 0,
                    weight = if (weight >= 0.0) weight else 0.0,
                )

                // Call the callback to insert/update the exercise
                onSetUpsert(newWeightSet)
            },
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp)
        ) {
            if (weightSet == null) Text("Insert Weight Set", color = LightGray) else Text("Edit Weight Set", color = LightGray)
        }
    }
}
