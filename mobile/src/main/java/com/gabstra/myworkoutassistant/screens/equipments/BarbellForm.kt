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
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
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
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.AppPrimaryButton
import com.gabstra.myworkoutassistant.composables.AppSecondaryButton
import com.gabstra.myworkoutassistant.composables.CollapsibleSection
import com.gabstra.myworkoutassistant.composables.FormSectionTitle
import com.gabstra.myworkoutassistant.shared.DisabledContentGray
import com.gabstra.myworkoutassistant.composables.StandardDialog
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Plate
import java.util.UUID

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BarbellForm(
    onUpsert: (Barbell) -> Unit,
    onCancel: () -> Unit,
    barbell: Barbell? = null,
) {
    // ----- state -----
    val nameState = rememberSaveable { mutableStateOf(barbell?.name ?: "") }
    val sleeveLengthState = rememberSaveable { mutableStateOf(barbell?.sleeveLength?.toString() ?: "") }
    val barWeightState = rememberSaveable { mutableStateOf(barbell?.barWeight?.toString() ?: "") }

    // Saveable for primitives/strings only. Keep complex types as remember.
    val availablePlatesState = remember { mutableStateOf(barbell?.availablePlates ?: emptyList<Plate>()) }

    val newPlateWeightState = rememberSaveable { mutableStateOf("") }
    val newPlateThicknessState = rememberSaveable { mutableStateOf("") }
    val showAvailablePlateDialog = rememberSaveable { mutableStateOf(false) }

    var expandedPlates by rememberSaveable { mutableStateOf(false) }

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
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Color.Transparent,
                    navigationIconContentColor = MaterialTheme.colorScheme.onBackground,
                    actionIconContentColor = MaterialTheme.colorScheme.onBackground
                ),
                title = {
                    Text(
                        modifier = Modifier
                            .fillMaxWidth()
                            .basicMarquee(iterations = Int.MAX_VALUE),
                        text = if (barbell == null) "Insert Barbell" else "Edit Barbell",
                        textAlign = TextAlign.Center,
                        style = MaterialTheme.typography.titleLarge
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
                    IconButton(modifier = Modifier.alpha(0f), onClick = { }) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "Back"
                        )
                    }
                }
            )
        }
    ) { paddingValues ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
                .padding(vertical = Spacing.sm)
                .verticalScroll(scrollState)
                .padding(horizontal = Spacing.md),
            verticalArrangement = Arrangement.spacedBy(Spacing.md)
        ) {
            EquipmentFormSection(title = "Details") {
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    verticalArrangement = Arrangement.spacedBy(Spacing.md)
                ) {
                    OutlinedTextField(
                        value = nameState.value,
                        onValueChange = { nameState.value = it },
                        label = { Text("Name", style = MaterialTheme.typography.labelLarge) },
                        modifier = Modifier.fillMaxWidth()
                    )

                    OutlinedTextField(
                        value = sleeveLengthState.value,
                        onValueChange = {
                            if (it.isEmpty() || it.all { ch -> ch.isDigit() }) {
                                sleeveLengthState.value = it
                            }
                        },
                        label = { Text("Sleeve length (mm)", style = MaterialTheme.typography.labelLarge) },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.fillMaxWidth()
                    )

                    OutlinedTextField(
                        value = barWeightState.value,
                        onValueChange = {
                            if (it.isEmpty() || (it.all { ch -> ch.isDigit() || ch == '.' } && !it.startsWith("."))) {
                                barWeightState.value = it
                            }
                        },
                        label = { Text("Bar weight (kg)", style = MaterialTheme.typography.labelLarge) },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            }

            val platesSummary = "${availablePlatesState.value.size} plate pair${if (availablePlatesState.value.size == 1) "" else "s"}"
            CollapsibleSection(
                title = "Available plate pairs",
                summary = platesSummary,
                expanded = expandedPlates,
                onToggle = { expandedPlates = !expandedPlates },
                action = {
                    EquipmentAddButton(
                        contentDescription = "Add plate",
                        onClick = { showAvailablePlateDialog.value = true },
                    )
                },
            ) {
                availablePlatesState.value
                    .sortedBy { it.weight }
                    .forEachIndexed { index, plate ->
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = Spacing.xs),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text(
                                "${index + 1}) ${plate.weight} kg • ${plate.thickness} mm",
                                style = MaterialTheme.typography.bodyMedium
                            )
                            IconButton(
                                modifier = Modifier.size(35.dp),
                                onClick = {
                                    availablePlatesState.value = availablePlatesState.value - plate
                                }
                            ) {
                                Icon(Icons.Default.Delete, contentDescription = "Remove plate")
                            }
                        }
                    }
            }

            EquipmentFormActions(
                saveEnabled = nameState.value.isNotBlank() &&
                    sleeveLengthState.value.toIntOrNull() != null &&
                    availablePlatesState.value.isNotEmpty(),
                onCancel = onCancel,
                onSave = {
                    val newBarbell = Barbell(
                        id = barbell?.id ?: UUID.randomUUID(),
                        name = nameState.value.trim(),
                        availablePlates = availablePlatesState.value,
                        sleeveLength = sleeveLengthState.value.toIntOrNull() ?: 0,
                        barWeight = barWeightState.value.toDoubleOrNull() ?: 0.0
                    )
                    onUpsert(newBarbell)
                },
            )
        }
    }

    // Add plate dialog
    if (showAvailablePlateDialog.value) {
        StandardDialog(
            onDismissRequest = { showAvailablePlateDialog.value = false },
            title = "Add plate",
            body = {
                Column {
                    OutlinedTextField(
                        value = newPlateWeightState.value,
                        onValueChange = {
                            if (it.isEmpty() || (it.all { ch -> ch.isDigit() || ch == '.' } && !it.startsWith("."))) {
                                newPlateWeightState.value = it
                            }
                        },
                        label = { Text("Weight (kg)", style = MaterialTheme.typography.labelLarge) },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.fillMaxWidth()
                    )
                    Spacer(modifier = Modifier.height(Spacing.sm))
                    OutlinedTextField(
                        value = newPlateThicknessState.value,
                        onValueChange = {
                            if (it.isEmpty() || (it.all { ch -> ch.isDigit() || ch == '.' } && !it.startsWith("."))) {
                                newPlateThicknessState.value = it
                            }
                        },
                        label = { Text("Thickness (mm)", style = MaterialTheme.typography.labelLarge) },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            },
            confirmText = "Add",
            onConfirm = {
                val weight = newPlateWeightState.value.toDoubleOrNull()
                val thickness = newPlateThicknessState.value.toDoubleOrNull()
                if (weight != null && weight > 0 && thickness != null) {
                    availablePlatesState.value =
                        availablePlatesState.value + Plate(weight, thickness)
                    newPlateWeightState.value = ""
                    newPlateThicknessState.value = ""
                    showAvailablePlateDialog.value = false
                }
            },
            confirmEnabled = newPlateWeightState.value.isNotEmpty() &&
                    newPlateThicknessState.value.isNotEmpty(),
            dismissText = "Cancel",
            onDismissButton = { showAvailablePlateDialog.value = false }
        )
    }
}




