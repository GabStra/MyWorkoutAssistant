package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.DumbbellUnit
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbells
import com.gabstra.myworkoutassistant.shared.equipments.Plate
import java.util.UUID

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DumbbellsForm(
    onDumbbellsUpsert: (Dumbbells) -> Unit,
    onCancel: () -> Unit,
    dumbbells: Dumbbells? = null,
) {
    // Mutable state for form fields
    val nameState = remember { mutableStateOf(dumbbells?.name ?: "") }
    val maxAdditionalItemsState = remember { mutableStateOf((dumbbells?.maxAdditionalItems ?: 0).toString()) }
    val volumeMultiplierState = remember { mutableStateOf(dumbbells?.volumeMultiplier.toString()) }

    // State for dumbbells and plates
    val availableDumbbellsState = remember { mutableStateOf(dumbbells?.availableDumbbells ?: emptyList<DumbbellUnit>()) }
    val additionalPlatesState = remember { mutableStateOf(dumbbells?.additionalPlates ?: emptyList<Plate>()) }

    // State for new inputs
    val newDumbbellWeightState = remember { mutableStateOf("") }
    val newPlateWeightState = remember { mutableStateOf("") }
    val newPlateThicknessState = remember { mutableStateOf("") }

    // State for showing dialogs
    val showDumbbellDialog = remember { mutableStateOf(false) }
    val showAdditionalPlateDialog = remember { mutableStateOf(false) }

    val scrollState = rememberScrollState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
            .verticalScroll(scrollState),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        // Dumbbells name field
        OutlinedTextField(
            value = nameState.value,
            onValueChange = { nameState.value = it },
            label = { Text("Dumbbells Set Name") },
            modifier = Modifier.fillMaxWidth()
        )

        // Volume Multiplier field
        OutlinedTextField(
            value = volumeMultiplierState.value,
            onValueChange = {
                if (it.isEmpty() || it.all { char -> char.isDigit() || char == '.' }) {
                    volumeMultiplierState.value = it
                }
            },
            label = { Text("Volume Multiplier") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            modifier = Modifier.fillMaxWidth()
        )

        // Max Additional Items field
        OutlinedTextField(
            value = maxAdditionalItemsState.value,
            onValueChange = {
                if (it.isEmpty() || it.all { char -> char.isDigit() }) {
                    maxAdditionalItemsState.value = it
                }
            },
            label = { Text("Maximum Additional Plates") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            modifier = Modifier.fillMaxWidth()
        )

        // Available Dumbbells Section
        Card(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 8.dp)
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(16.dp)
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = "Available Dumbbells",
                        style = MaterialTheme.typography.titleMedium
                    )
                    IconButton(onClick = { showDumbbellDialog.value = true }) {
                        Icon(Icons.Default.Add, contentDescription = "Add Dumbbell")
                    }
                }

                availableDumbbellsState.value.sortedBy { it.weight }.forEach { dumbbell ->
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 4.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text("${dumbbell.weight}kg")
                        IconButton(
                            onClick = {
                                availableDumbbellsState.value = availableDumbbellsState.value - dumbbell
                            }
                        ) {
                            Icon(Icons.Default.Delete, contentDescription = "Remove Dumbbell")
                        }
                    }
                }
            }
        }

        // Additional Plates Section
        Card(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 8.dp)
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(16.dp)
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = "Additional Plates",
                        style = MaterialTheme.typography.titleMedium
                    )
                    IconButton(onClick = { showAdditionalPlateDialog.value = true }) {
                        Icon(Icons.Default.Add, contentDescription = "Add Plate")
                    }
                }

                additionalPlatesState.value.sortedBy { it.weight }.forEach { plate ->
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 4.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text("${plate.weight}kg - ${plate.thickness}mm")
                        IconButton(
                            onClick = {
                                additionalPlatesState.value = additionalPlatesState.value - plate
                            }
                        ) {
                            Icon(Icons.Default.Delete, contentDescription = "Remove Plate")
                        }
                    }
                }
            }
        }

        // Submit button
        Button(
            colors = ButtonDefaults.buttonColors(contentColor = MaterialTheme.colorScheme.background),
            onClick = {
                val newDumbbells = Dumbbells(
                    id = dumbbells?.id ?: UUID.randomUUID(),
                    name = nameState.value.trim(),
                    availableDumbbells = availableDumbbellsState.value,
                    additionalPlates = additionalPlatesState.value,
                    maxAdditionalItems = maxAdditionalItemsState.value.toIntOrNull() ?: 0,
                    volumeMultiplier = volumeMultiplierState.value.toDoubleOrNull() ?: 1.0
                )
                onDumbbellsUpsert(newDumbbells)
            },
            modifier = Modifier.fillMaxWidth(),
            enabled = nameState.value.isNotBlank() && availableDumbbellsState.value.isNotEmpty()
        ) {
            if (dumbbells == null) Text("Add Dumbbells Set") else Text("Edit Dumbbells Set")
        }

        // Cancel button
        Button(
            colors = ButtonDefaults.buttonColors(contentColor = MaterialTheme.colorScheme.background),
            onClick = onCancel,
            modifier = Modifier.fillMaxWidth()
        ) {
            Text("Cancel")
        }
    }

    // Dialog for adding new dumbbell
    if (showDumbbellDialog.value) {
        AlertDialog(
            onDismissRequest = { showDumbbellDialog.value = false },
            title = { Text("Add Dumbbell") },
            text = {
                Column {
                    OutlinedTextField(
                        value = newDumbbellWeightState.value,
                        onValueChange = {
                            if (it.isEmpty() || (it.all { it.isDigit() || it == '.' } && !it.startsWith("."))) {
                                newDumbbellWeightState.value = it
                            }
                        },
                        label = { Text("Weight (kg)") },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        val weight = newDumbbellWeightState.value.toDoubleOrNull()
                        if (weight != null && weight > 0) {
                            availableDumbbellsState.value += DumbbellUnit(weight)
                            newDumbbellWeightState.value = ""
                            showDumbbellDialog.value = false
                        }
                    },
                    enabled = newDumbbellWeightState.value.isNotEmpty()
                ) {
                    Text("Add")
                }
            },
            dismissButton = {
                TextButton(onClick = { showDumbbellDialog.value = false }) {
                    Text("Cancel")
                }
            }
        )
    }

    // Dialog for adding new additional plate
    if (showAdditionalPlateDialog.value) {
        AlertDialog(
            onDismissRequest = { showAdditionalPlateDialog.value = false },
            title = { Text("Add Additional Plate") },
            text = {
                Column {
                    OutlinedTextField(
                        value = newPlateWeightState.value,
                        onValueChange = {
                            if (it.isEmpty() || (it.all { it.isDigit() || it == '.' } && !it.startsWith("."))) {
                                newPlateWeightState.value = it
                            }
                        },
                        label = { Text("Weight (kg)") },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.fillMaxWidth()
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    OutlinedTextField(
                        value = newPlateThicknessState.value,
                        onValueChange = {
                            if (it.isEmpty() || (it.all { it.isDigit() || it == '.' } && !it.startsWith("."))) {
                                newPlateThicknessState.value = it
                            }
                        },
                        label = { Text("Thickness (mm)") },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        val weight = newPlateWeightState.value.toDoubleOrNull()
                        val thickness = newPlateThicknessState.value.toDoubleOrNull()
                        if (weight != null && weight > 0 && thickness != null) {
                            additionalPlatesState.value = additionalPlatesState.value + Plate(weight, thickness)
                            newPlateWeightState.value = ""
                            newPlateThicknessState.value = ""
                            showAdditionalPlateDialog.value = false
                        }
                    },
                    enabled = newPlateWeightState.value.isNotEmpty() &&
                            newPlateThicknessState.value.isNotEmpty()
                ) {
                    Text("Add")
                }
            },
            dismissButton = {
                TextButton(onClick = { showAdditionalPlateDialog.value = false }) {
                    Text("Cancel")
                }
            }
        )
    }
}