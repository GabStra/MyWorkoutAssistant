package com.gabstra.myworkoutassistant.screens.equipments

import androidx.compose.foundation.background
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.composables.CustomButton
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.shared.equipments.BaseWeight
import com.gabstra.myworkoutassistant.shared.equipments.Machine
import com.gabstra.myworkoutassistant.verticalColumnScrollbar
import java.util.UUID

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MachineForm(
    onUpsert: (Machine) -> Unit,
    onCancel: () -> Unit,
    machine: Machine? = null,
) {
    // Mutable state for form fields
    val nameState = remember { mutableStateOf(machine?.name ?: "") }

    val maxExtraWeightsPerLoadingPointState = remember { mutableStateOf((machine?.maxExtraWeightsPerLoadingPoint ?: 0).toString()) }
    // State for plates
    val availableWeightsState = remember { mutableStateOf(machine?.availableWeights ?: emptyList<BaseWeight>()) }
    val extraWeightsState = remember { mutableStateOf(machine?.extraWeights ?: emptyList<BaseWeight>()) }


    // State for new plate inputs
    val newWeightState = remember { mutableStateOf("") }
    val newExtraWeightState = remember { mutableStateOf("") }

    // State for showing dialogs
    val showAvailableWeightsDialog = remember { mutableStateOf(false) }

    val showExtraWeightDialog = remember { mutableStateOf(false) }

    val scrollState = rememberScrollState()
    val outlineVariant = MaterialTheme.colorScheme.outlineVariant

    Scaffold(
        topBar = {
            TopAppBar(
                modifier = Modifier.drawBehind {
                    drawLine(
                        color = outlineVariant,
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
                        color = MaterialTheme.colorScheme.onBackground,
                        text = if(machine == null) "Insert Machine" else "Edit Machine"
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
    ) { it ->

        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(it)
                .padding(top = 10.dp)
                .verticalColumnScrollbar(scrollState)
                .verticalScroll(scrollState)
                .padding(horizontal = 15.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            // Barbell name field
            OutlinedTextField(
                value = nameState.value,
                onValueChange = { nameState.value = it },
                label = { Text("Machine Name") },
                modifier = Modifier.fillMaxWidth()
            )

            OutlinedTextField(
                value = maxExtraWeightsPerLoadingPointState.value,
                onValueChange = {
                    if (it.isEmpty() || it.all { char -> char.isDigit() }) {
                        maxExtraWeightsPerLoadingPointState.value = it
                    }
                },
                label = { Text("Maximum Additional Weights") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.fillMaxWidth()
            )

            // Available Plates Section
            StyledCard(
                modifier = Modifier
                    .fillMaxWidth(),
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(10.dp),
                    verticalArrangement = Arrangement.spacedBy(5.dp)
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            text = "Available Weights",
                            style = MaterialTheme.typography.titleMedium
                        )
                        IconButton(modifier= Modifier.clip(CircleShape).background(MaterialTheme.colorScheme.primary).size(35.dp),onClick = { showAvailableWeightsDialog.value = true }) {
                            Icon(imageVector = Icons.Default.Add, contentDescription = "Add Weight", tint = MaterialTheme.colorScheme.onPrimary)
                        }
                    }

                    availableWeightsState.value.sortedBy { it.weight }.forEachIndexed { index, weight ->
                        Row(
                            modifier = Modifier
                                .fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text("${index+1}) ${weight.weight}kg",style = MaterialTheme.typography.bodyMedium)
                            IconButton(
                                modifier = Modifier.size(35.dp),
                                onClick = {
                                    availableWeightsState.value = availableWeightsState.value - weight
                                }
                            ) {
                                Icon(Icons.Default.Delete, contentDescription = "Remove Plate")
                            }
                        }
                    }
                }
            }

            StyledCard(
                modifier = Modifier
                    .fillMaxWidth(),
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(10.dp)
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            text = "Extra Weights",
                            style = MaterialTheme.typography.titleMedium
                        )
                        IconButton(modifier= Modifier.clip(CircleShape).background(MaterialTheme.colorScheme.primary).size(35.dp),onClick = { showExtraWeightDialog.value = true }) {
                            Icon(imageVector = Icons.Default.Add,  contentDescription = "Add Extra Weight", tint = MaterialTheme.colorScheme.onPrimary)
                        }
                    }

                    extraWeightsState.value.sortedBy { it.weight }.forEachIndexed { index, plate ->
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = 4.dp),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text("${index+1}) ${plate.weight}kg",
                                style = MaterialTheme.typography.bodyMedium
                            )
                            IconButton(
                                modifier = Modifier.size(35.dp),
                                onClick = {
                                    extraWeightsState.value =
                                        extraWeightsState.value - plate
                                }
                            ) {
                                Icon(Icons.Default.Delete, contentDescription = "Remove Weight")
                            }
                        }
                    }
                }
            }

            // Submit button
            Button(
                colors = ButtonDefaults.buttonColors(
                    contentColor = MaterialTheme.colorScheme.background,
                    disabledContentColor = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.38f)
                ),
                onClick = {
                    val newMachine = Machine(
                        id = machine?.id ?: UUID.randomUUID(),
                        name = nameState.value.trim(),
                        availableWeights = availableWeightsState.value,
                        extraWeights = extraWeightsState.value,
                        maxExtraWeightsPerLoadingPoint = maxExtraWeightsPerLoadingPointState.value.toIntOrNull() ?: 0,
                    )
                    onUpsert(newMachine)
                },
                modifier = Modifier.fillMaxWidth(),
                enabled = nameState.value.isNotBlank() &&
                        availableWeightsState.value.isNotEmpty()
            ) {
                if (machine == null) Text("Add Machine", color = MaterialTheme.colorScheme.onPrimary) else Text("Edit Machine", color = MaterialTheme.colorScheme.onPrimary)
            }

            // Cancel button
            CustomButton(
                text = "Cancel",
                onClick = {
                    onCancel()
                },
                modifier = Modifier.fillMaxWidth()
            )
        }
    }
    // Dialog for adding new available plate
    if (showAvailableWeightsDialog.value) {
        AlertDialog(
            onDismissRequest = { showAvailableWeightsDialog.value = false },
            title = { Text("Add Weight", color = MaterialTheme.colorScheme.onPrimary) },
            text = {
                Column {
                    OutlinedTextField(
                        value = newWeightState.value,
                        onValueChange = {
                            if (it.isEmpty() || (it.all { it.isDigit() || it == '.' } && !it.startsWith("."))) {
                                newWeightState.value = it
                            }
                        },
                        label = { Text("Weight (KG)") },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        val weight = newWeightState.value.toDoubleOrNull()
                        if (weight != null && weight > 0) {
                            availableWeightsState.value = availableWeightsState.value + BaseWeight(weight)
                            availableWeightsState.value = availableWeightsState.value.distinctBy { it.weight }
                            newWeightState.value = ""
                            showAvailableWeightsDialog.value = false
                        }
                    },
                    enabled = newWeightState.value.isNotEmpty()
                ) {
                    Text("Add")
                }
            },
            dismissButton = {
                TextButton(onClick = { showAvailableWeightsDialog.value = false }) {
                    Text("Cancel")
                }
            }
        )
    }

    if (showExtraWeightDialog.value) {
        AlertDialog(
            onDismissRequest = { showExtraWeightDialog.value = false },
            title = { Text("Add Extra Weight", color = MaterialTheme.colorScheme.onPrimary) },
            text = {
                Column {
                    OutlinedTextField(
                        value = newExtraWeightState.value,
                        onValueChange = {
                            if (it.isEmpty() || (it.all { it.isDigit() || it == '.' } && !it.startsWith("."))) {
                                newExtraWeightState.value = it
                            }
                        },
                        label = { Text("Weight (KG)") },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        val weight = newExtraWeightState.value.toDoubleOrNull()
                        if (weight != null && weight > 0) {
                            extraWeightsState.value = extraWeightsState.value + BaseWeight(weight)
                            newExtraWeightState.value = ""
                            showExtraWeightDialog.value = false
                        }
                    },
                    enabled = newExtraWeightState.value.isNotEmpty()
                ) {
                    Text("Add")
                }
            },
            dismissButton = {
                TextButton(onClick = { showExtraWeightDialog.value = false }) {
                    Text("Cancel")
                }
            }
        )
    }
}