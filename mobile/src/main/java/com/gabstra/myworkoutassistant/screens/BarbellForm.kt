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
import com.gabstra.myworkoutassistant.shared.equipments.Plate
import java.util.UUID

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BarbellForm(
    onBarbellUpsert: (Barbell) -> Unit,
    onCancel: () -> Unit,
    barbell: Barbell? = null,
) {
    // Mutable state for form fields
    val nameState = remember { mutableStateOf(barbell?.name ?: "") }
    val barLengthState = remember { mutableStateOf(barbell?.barLength?.toString() ?: "") }
    val maxAdditionalItemsState = remember { mutableStateOf((barbell?.maxAdditionalItems ?: 0).toString()) }

    // State for plates
    val availablePlatesState = remember { mutableStateOf(barbell?.availablePlates ?: emptyList<Plate>()) }
    val additionalPlatesState = remember { mutableStateOf(barbell?.additionalPlates ?: emptyList<Plate>()) }

    // State for new plate inputs
    val newPlateWeightState = remember { mutableStateOf("") }
    val newPlateThicknessState = remember { mutableStateOf("") }

    // State for showing dialogs
    val showAvailablePlateDialog = remember { mutableStateOf(false) }
    val showAdditionalPlateDialog = remember { mutableStateOf(false) }

    val scrollState = rememberScrollState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
            .verticalScroll(scrollState),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        // Barbell name field
        OutlinedTextField(
            value = nameState.value,
            onValueChange = { nameState.value = it },
            label = { Text("Barbell Name") },
            modifier = Modifier.fillMaxWidth()
        )

        // Bar length field
        OutlinedTextField(
            value = barLengthState.value,
            onValueChange = {
                if (it.isEmpty() || it.all { char -> char.isDigit() }) {
                    barLengthState.value = it
                }
            },
            label = { Text("Bar Length (mm)") },
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

        // Available Plates Section
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
                        text = "Available Plates",
                        style = MaterialTheme.typography.titleMedium
                    )
                    IconButton(onClick = { showAvailablePlateDialog.value = true }) {
                        Icon(Icons.Default.Add, contentDescription = "Add Plate")
                    }
                }

                availablePlatesState.value.sortedBy { it.weight }.forEach { plate ->
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
                                availablePlatesState.value = availablePlatesState.value - plate
                            }
                        ) {
                            Icon(Icons.Default.Delete, contentDescription = "Remove Plate")
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
                val newBarbell = Barbell(
                    id = barbell?.id ?: UUID.randomUUID(),
                    name = nameState.value.trim(),
                    availablePlates = availablePlatesState.value,
                    barLength = barLengthState.value.toIntOrNull() ?: 0,
                    additionalPlates = additionalPlatesState.value,
                    maxAdditionalItems = maxAdditionalItemsState.value.toIntOrNull() ?: 0
                )
                onBarbellUpsert(newBarbell)
            },
            modifier = Modifier.fillMaxWidth(),
            enabled = nameState.value.isNotBlank() &&
                    barLengthState.value.isNotBlank() &&
                    barLengthState.value.toIntOrNull() != null &&
                    availablePlatesState.value.isNotEmpty()
        ) {
            if (barbell == null) Text("Add Barbell") else Text("Edit Barbell")
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

    // Dialog for adding new available plate
    if (showAvailablePlateDialog.value) {
        AlertDialog(
            onDismissRequest = { showAvailablePlateDialog.value = false },
            title = { Text("Add Available Plate") },
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
                            availablePlatesState.value = availablePlatesState.value + Plate(weight, thickness)
                            newPlateWeightState.value = ""
                            newPlateThicknessState.value = ""
                            showAvailablePlateDialog.value = false
                        }
                    },
                    enabled = newPlateWeightState.value.isNotEmpty() &&
                            newPlateThicknessState.value.isNotEmpty()
                ) {
                    Text("Add")
                }
            },
            dismissButton = {
                TextButton(onClick = { showAvailablePlateDialog.value = false }) {
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