package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.BorderStroke
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
import androidx.compose.material3.DropdownMenu
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.DarkGray
import com.gabstra.myworkoutassistant.shared.LightGray
import com.gabstra.myworkoutassistant.shared.MediumGray
import com.gabstra.myworkoutassistant.verticalColumnScrollbar
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.util.UUID

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WeightSetForm(
    onSetUpsert: (Set) -> Unit,
    weightSet: WeightSet? = null,
    equipment: WeightLoadedEquipment
) {
    // Mutable state for form fields
    val repsState = remember { mutableStateOf(weightSet?.reps?.toString() ?: "") }
    val weightState = remember { mutableStateOf(weightSet?.weight?.toString() ?: "") }

    var possibleCombinations by remember { mutableStateOf<kotlin.collections.Set<Pair<Double, String>>>(emptySet())}

    LaunchedEffect(Unit) {
        withContext(Dispatchers.IO) {
            possibleCombinations = equipment.getWeightsCombinationsWithLabels()
        }
    }

    val filterState = remember { mutableStateOf("") }

    val filteredCombinations = remember(filterState.value,possibleCombinations) {
        if( filterState.value.isEmpty()) {
            possibleCombinations
        } else {
            possibleCombinations.filter { (_,label) ->
                label.contains(filterState.value, ignoreCase = true)
            }
        }
    }

    val expandedWeights = remember { mutableStateOf(false) }

    Column(
        modifier = Modifier
            .fillMaxWidth(),
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

        if(possibleCombinations.isNotEmpty()){
            Box{
                Box {
                    OutlinedTextField(
                        value = weightState.value,
                        readOnly = true,
                        onValueChange = {},
                        label = { Text("Weight (kg)") },
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(8.dp)
                    )
                    Box(
                        modifier = Modifier
                            .matchParentSize()
                            .clickable { expandedWeights.value = true }
                    )
                }

                val scrollState = rememberScrollState()

                DropdownMenu(
                    expanded = expandedWeights.value,
                    onDismissRequest = { expandedWeights.value = false },
                    border = BorderStroke(1.dp, MediumGray),
                    modifier = Modifier.fillMaxWidth(.75f),
                    containerColor =  DarkGray
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
                            modifier = Modifier
                                .fillMaxWidth(),
                        )
                        Column(
                            modifier = Modifier
                                .padding(top = 5.dp)
                                .height(300.dp)
                                .fillMaxWidth()
                                .verticalColumnScrollbar(scrollState)
                                .verticalScroll(scrollState)
                                .padding(horizontal = 15.dp),
                            verticalArrangement = Arrangement.spacedBy(5.dp)
                        ) {
                            filteredCombinations.forEach { (combo,label) ->
                                StyledCard {
                                    Row(
                                        modifier = Modifier.fillMaxWidth().padding(5.dp),
                                        horizontalArrangement = Arrangement.Center,
                                        verticalAlignment = Alignment.CenterVertically
                                    ) {
                                        Text(
                                            modifier = Modifier.clickable{
                                                expandedWeights.value = false
                                                weightState.value = combo.toString()
                                            },
                                            text = label
                                        )
                                    }
                                }
                            }
                        }

                    }
                }
            }
        }else{
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp),
                contentAlignment = Alignment.Center
            ){
                CircularProgressIndicator(
                    modifier = Modifier.width(32.dp),
                    color = MaterialTheme.colorScheme.primary,
                    trackColor = Color.DarkGray,
                )
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
            if (weightSet == null) Text("Insert Weight Set", color = DarkGray) else Text("Edit Weight Set", color = DarkGray)
        }
    }
}
