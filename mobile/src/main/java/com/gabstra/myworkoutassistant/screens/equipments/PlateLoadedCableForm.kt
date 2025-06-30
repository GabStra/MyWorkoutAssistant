package com.gabstra.myworkoutassistant.screens.equipments

import androidx.compose.foundation.background
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
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
import com.gabstra.myworkoutassistant.shared.equipments.Plate
import com.gabstra.myworkoutassistant.shared.equipments.PlateLoadedCable
import com.gabstra.myworkoutassistant.shared.MediumLightGray
import com.gabstra.myworkoutassistant.verticalColumnScrollbar
import java.util.UUID

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PlateLoadedCableForm(
    onUpsert: (PlateLoadedCable) -> Unit,
    onCancel: () -> Unit,
    plateLoadedCable: PlateLoadedCable? = null,
) {
    // Mutable state for form fields
    val nameState = remember { mutableStateOf(plateLoadedCable?.name ?: "") }
    val barLengthState = remember { mutableStateOf(plateLoadedCable?.barLength?.toString() ?: "") }

    // State for plates
    val availablePlatesState = remember { mutableStateOf(plateLoadedCable?.availablePlates ?: emptyList<Plate>()) }

    // State for new plate inputs
    val newPlateWeightState = remember { mutableStateOf("") }
    val newPlateThicknessState = remember { mutableStateOf("") }

    // State for showing dialogs
    val showAvailablePlateDialog = remember { mutableStateOf(false) }

    val scrollState = rememberScrollState()

    Scaffold(
        topBar = {
            TopAppBar(
                modifier = Modifier.drawBehind {
                    drawLine(
                        color = MediumLightGray,
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
                        text = if(plateLoadedCable == null) "Insert Plate-Loaded Cable" else "Edit Plate-Loaded Cable"
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
                label = { Text("Plate-Loaded Cable Name") },
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
                            text = "Available Plates",
                            style = MaterialTheme.typography.titleMedium
                        )
                        IconButton(modifier= Modifier.clip(CircleShape).background(MaterialTheme.colorScheme.primary).size(35.dp),onClick = { showAvailablePlateDialog.value = true }) {
                            Icon(imageVector = Icons.Default.Add, contentDescription = "Add Plate")
                        }
                    }

                    availablePlatesState.value.sortedBy { it.weight }.forEachIndexed { index, plate ->
                        Row(
                            modifier = Modifier
                                .fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text("${index+1}) ${plate.weight}kg - ${plate.thickness}mm",style = MaterialTheme.typography.bodyMedium)
                            IconButton(
                                modifier = Modifier.size(35.dp),
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

            // Submit button
            Button(
                colors = ButtonDefaults.buttonColors(contentColor = MaterialTheme.colorScheme.background),
                onClick = {
                    val newPlateLoadedCable = PlateLoadedCable(
                        id = plateLoadedCable?.id ?: UUID.randomUUID(),
                        name = nameState.value.trim(),
                        availablePlates = availablePlatesState.value,
                        barLength = barLengthState.value.toIntOrNull() ?: 0,
                    )
                    onUpsert(newPlateLoadedCable)
                },
                modifier = Modifier.fillMaxWidth(),
                enabled = nameState.value.isNotBlank() &&
                        barLengthState.value.isNotBlank() &&
                        barLengthState.value.toIntOrNull() != null &&
                        availablePlatesState.value.isNotEmpty()
            ) {
                if (plateLoadedCable == null) Text("Add Plate-Loaded Cable") else Text("Edit Plate-Loaded Cable")
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
}