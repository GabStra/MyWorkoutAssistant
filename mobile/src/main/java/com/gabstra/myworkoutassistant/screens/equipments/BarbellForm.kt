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
                        text = if (barbell == null) stringResource(R.string.equipment_insert_barbell) else stringResource(R.string.equipment_edit_barbell),
                        textAlign = TextAlign.Center,
                        style = MaterialTheme.typography.titleLarge
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
                    IconButton(modifier = Modifier.alpha(0f), onClick = { }) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = stringResource(R.string.equipment_back)
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
                            if (it.isEmpty() || it.all { ch -> ch.isDigit() }) {
                                sleeveLengthState.value = it
                            }
                        },
                        label = { Text(stringResource(R.string.equipment_sleeve_length_mm), style = MaterialTheme.typography.labelLarge) },
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
                        label = { Text(stringResource(R.string.equipment_bar_weight_kg), style = MaterialTheme.typography.labelLarge) },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            }

            val platesSummary = pluralStringResource(
                R.plurals.equipment_plate_pair_count,
                availablePlatesState.value.size,
                availablePlatesState.value.size
            )
            CollapsibleSection(
                title = stringResource(R.string.equipment_available_plate_pairs),
                summary = platesSummary,
                expanded = expandedPlates,
                onToggle = { expandedPlates = !expandedPlates },
                expandedContentSpacing = Spacing.sm,
                footerAction = {
                    EquipmentAddButton(
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
                                stringResource(R.string.equipment_plate_entry, index + 1, plate.weight, plate.thickness),
                                style = MaterialTheme.typography.bodyMedium
                            )
                            IconButton(
                            modifier = Modifier.size(32.dp),
                                onClick = {
                                    availablePlatesState.value = availablePlatesState.value - plate
                                }
                            ) {
                                Icon(Icons.Default.Delete, contentDescription = stringResource(R.string.equipment_remove_plate_lowercase))
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
            title = stringResource(R.string.equipment_add_plate),
            body = {
                Column {
                    OutlinedTextField(
                        value = newPlateWeightState.value,
                        onValueChange = {
                            if (it.isEmpty() || (it.all { ch -> ch.isDigit() || ch == '.' } && !it.startsWith("."))) {
                                newPlateWeightState.value = it
                            }
                        },
                        label = { Text(stringResource(R.string.equipment_weight_kg_lowercase), style = MaterialTheme.typography.labelLarge) },
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
                        label = { Text(stringResource(R.string.equipment_thickness_mm), style = MaterialTheme.typography.labelLarge) },
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
                    availablePlatesState.value =
                        availablePlatesState.value + Plate(weight, thickness)
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




