package com.gabstra.myworkoutassistant.screens.equipments

import com.gabstra.myworkoutassistant.composables.BreadcrumbScaffold

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
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.AppPrimaryButton
import com.gabstra.myworkoutassistant.composables.AppSecondaryButton
import com.gabstra.myworkoutassistant.composables.CollapsibleSection
import com.gabstra.myworkoutassistant.composables.FormSectionTitle
import com.gabstra.myworkoutassistant.shared.DisabledContentGray
import com.gabstra.myworkoutassistant.composables.StandardDialog
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.shared.equipments.Plate
import com.gabstra.myworkoutassistant.shared.equipments.PlateLoadedCable
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
    val sleeveLengthState = remember { mutableStateOf(plateLoadedCable?.sleeveLength?.toString() ?: "") }

    // State for plates
    val availablePlatesState = remember { mutableStateOf(plateLoadedCable?.availablePlates ?: emptyList<Plate>()) }

    // State for new plate inputs
    val newPlateWeightState = remember { mutableStateOf("") }
    val newPlateThicknessState = remember { mutableStateOf("") }

    // State for showing dialogs
    val showAvailablePlateDialog = remember { mutableStateOf(false) }

    var expandedPlates by remember { mutableStateOf(false) }

    val scrollState = rememberScrollState()

    BreadcrumbScaffold(
        topBar = {
            TopAppBar(
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
                        textAlign = TextAlign.Center,
                        text = if(plateLoadedCable == null) stringResource(R.string.equipment_insert_plate_loaded_cable) else stringResource(R.string.equipment_edit_plate_loaded_cable)
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onCancel) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = stringResource(R.string.equipment_back)
                        )
                    }
                },
                actions = {
                    IconButton(modifier = Modifier.alpha(0f), onClick = {
                        onCancel()
                    }) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = stringResource(R.string.equipment_back)
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
                .padding(vertical = Spacing.sm)
                .verticalScroll(scrollState)
                .padding(horizontal = Spacing.md),
            verticalArrangement = Arrangement.spacedBy(Spacing.sm)
        ) {
            EquipmentFormSection(title = stringResource(R.string.equipment_details)) {
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    verticalArrangement = Arrangement.spacedBy(Spacing.sm)
                ) {
                    OutlinedTextField(
                        value = nameState.value,
                        onValueChange = { nameState.value = it },
                        label = { Text(stringResource(R.string.equipment_name_label), style = MaterialTheme.typography.labelLarge) },
                        modifier = Modifier.fillMaxWidth()
                    )
                    OutlinedTextField(
                        value = sleeveLengthState.value,
                        onValueChange = {
                            if (it.isEmpty() || it.all { char -> char.isDigit() }) {
                                sleeveLengthState.value = it
                            }
                        },
                        label = { Text(stringResource(R.string.equipment_sleeve_length_mm), style = MaterialTheme.typography.labelLarge) },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            }

            CollapsibleSection(
                title = stringResource(R.string.equipment_available_plates),
                summary = pluralStringResource(
                    R.plurals.equipment_plate_pair_count,
                    availablePlatesState.value.size,
                    availablePlatesState.value.size
                ),
                expanded = expandedPlates,
                onToggle = { expandedPlates = !expandedPlates },
                expandedContentSpacing = Spacing.sm,
                footerAction = {
                    EquipmentAddButton(
                        onClick = { showAvailablePlateDialog.value = true },
                    )
                },
            ) {
                availablePlatesState.value.sortedBy { it.weight }.forEachIndexed { index, plate ->
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = Spacing.xs),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(stringResource(R.string.equipment_plate_entry_compact, index + 1, plate.weight, plate.thickness), style = MaterialTheme.typography.bodyMedium)
                        IconButton(
                            modifier = Modifier.size(32.dp),
                            onClick = {
                                availablePlatesState.value = availablePlatesState.value - plate
                            }
                        ) {
                            Icon(Icons.Default.Delete, contentDescription = stringResource(R.string.equipment_remove_plate))
                        }
                    }
                }
            }

            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = Spacing.sm),
                horizontalArrangement = Arrangement.spacedBy(Spacing.md),
                verticalAlignment = Alignment.CenterVertically
            ) {
                AppSecondaryButton(
                    text = stringResource(R.string.equipment_cancel),
                    onClick = {
                        onCancel()
                    },
                    modifier = Modifier.weight(1f)
                )

                AppPrimaryButton(
                    text = stringResource(R.string.equipment_save),
                    onClick = {
                        val newPlateLoadedCable = PlateLoadedCable(
                            id = plateLoadedCable?.id ?: UUID.randomUUID(),
                            name = nameState.value.trim(),
                            availablePlates = availablePlatesState.value,
                            sleeveLength = sleeveLengthState.value.toIntOrNull() ?: 0,
                        )
                        onUpsert(newPlateLoadedCable)
                    },
                    enabled = nameState.value.isNotBlank() &&
                            sleeveLengthState.value.isNotBlank() &&
                            sleeveLengthState.value.toIntOrNull() != null &&
                            availablePlatesState.value.isNotEmpty(),
                    modifier = Modifier.weight(1f)
                )
            }
        }
    }
    // Dialog for adding new available plate
    if (showAvailablePlateDialog.value) {
        StandardDialog(
            onDismissRequest = { showAvailablePlateDialog.value = false },
            title = stringResource(R.string.equipment_add_available_plate),
            body = {
                Column {
                    OutlinedTextField(
                        value = newPlateWeightState.value,
                        onValueChange = {
                            if (it.isEmpty() || (it.all { it.isDigit() || it == '.' } && !it.startsWith("."))) {
                                newPlateWeightState.value = it
                            }
                        },
                        label = { Text(stringResource(R.string.equipment_weight_kg_label)) },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.fillMaxWidth()
                    )
                    Spacer(modifier = Modifier.height(Spacing.sm))
                    OutlinedTextField(
                        value = newPlateThicknessState.value,
                        onValueChange = {
                            if (it.isEmpty() || (it.all { it.isDigit() || it == '.' } && !it.startsWith("."))) {
                                newPlateThicknessState.value = it
                            }
                        },
                        label = { Text(stringResource(R.string.equipment_thickness_mm)) },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            },
            confirmText = stringResource(R.string.equipment_add),
            onConfirm = {
                val weight = newPlateWeightState.value.toDoubleOrNull()
                val thickness = newPlateThicknessState.value.toDoubleOrNull()
                if (weight != null && weight > 0 && thickness != null) {
                    availablePlatesState.value = availablePlatesState.value + Plate(weight, thickness)
                    newPlateWeightState.value = ""
                    newPlateThicknessState.value = ""
                    showAvailablePlateDialog.value = false
                }
            },
            confirmEnabled = newPlateWeightState.value.isNotEmpty() &&
                    newPlateThicknessState.value.isNotEmpty(),
            dismissText = stringResource(R.string.equipment_cancel),
            onDismissButton = { showAvailablePlateDialog.value = false }
        )
    }
}




