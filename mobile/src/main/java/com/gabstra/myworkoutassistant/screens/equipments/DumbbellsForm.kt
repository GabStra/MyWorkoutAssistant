package com.gabstra.myworkoutassistant.screens.equipments

import com.gabstra.myworkoutassistant.composables.BreadcrumbScaffold

import androidx.compose.foundation.background
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
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
import com.gabstra.myworkoutassistant.shared.equipments.BaseWeight
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbells
import java.util.UUID

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DumbbellsForm(
    onUpsert: (Dumbbells) -> Unit,
    onCancel: () -> Unit,
    dumbbells: Dumbbells? = null,
) {
    // Mutable state for form fields
    val nameState = remember { mutableStateOf(dumbbells?.name ?: "") }
    val maxExtraWeightsPerLoadingPointState = remember { mutableStateOf((dumbbells?.maxExtraWeightsPerLoadingPoint ?: 0).toString()) }

    // State for dumbbells and plates
    val availableDumbbellsState = remember { mutableStateOf(dumbbells?.availableDumbbells ?: emptyList<BaseWeight>()) }
    val extraWeightsState = remember { mutableStateOf(dumbbells?.extraWeights ?: emptyList<BaseWeight>()) }

    // State for new inputs
    val newDumbbellWeightState = remember { mutableStateOf("") }
    val newExtraWeightState = remember { mutableStateOf("") }

    // State for showing dialogs
    val showDumbbellDialog = remember { mutableStateOf(false) }
    val showExtraWeightDialog = remember { mutableStateOf(false) }

    var expandedDumbbells by remember { mutableStateOf(false) }
    var expandedExtraWeights by remember { mutableStateOf(false) }

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
                        color = MaterialTheme.colorScheme.onBackground,
                        textAlign = TextAlign.Center,
                        text = if (dumbbells == null) stringResource(R.string.equipment_insert_dumbbell_pair) else stringResource(R.string.equipment_edit_dumbbell_pair)
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
                    IconButton(modifier = Modifier.alpha(0f), onClick = { onCancel() }) {
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
                        value = maxExtraWeightsPerLoadingPointState.value,
                        onValueChange = {
                            if (it.isEmpty() || it.all { char -> char.isDigit() }) {
                                maxExtraWeightsPerLoadingPointState.value = it
                            }
                        },
                        label = { Text(stringResource(R.string.equipment_max_additional_plates), style = MaterialTheme.typography.labelLarge) },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            }

            CollapsibleSection(
                title = stringResource(R.string.equipment_available_dumbbell_pairs),
                summary = pluralStringResource(
                    R.plurals.equipment_pair_count,
                    availableDumbbellsState.value.size,
                    availableDumbbellsState.value.size
                ),
                expanded = expandedDumbbells,
                onToggle = { expandedDumbbells = !expandedDumbbells },
                expandedContentSpacing = Spacing.sm,
                footerAction = {
                    EquipmentAddButton(
                        onClick = { showDumbbellDialog.value = true },
                    )
                },
            ) {
                availableDumbbellsState.value.sortedBy { it.weight }.forEachIndexed { index, dumbbell ->
                    Row(
                        modifier = Modifier.fillMaxWidth().padding(vertical = Spacing.xs),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(stringResource(R.string.equipment_weight_entry, index + 1, dumbbell.weight), style = MaterialTheme.typography.bodyMedium)
                        IconButton(
                            modifier = Modifier.size(32.dp),
                            onClick = {
                                availableDumbbellsState.value =
                                    availableDumbbellsState.value - dumbbell
                            }
                        ) {
                            Icon(Icons.Default.Delete, contentDescription = stringResource(R.string.equipment_remove_dumbbell_pair))
                        }
                    }
                }
            }

            CollapsibleSection(
                title = stringResource(R.string.equipment_extra_weights),
                summary = stringResource(R.string.equipment_weights_count, extraWeightsState.value.size),
                expanded = expandedExtraWeights,
                onToggle = { expandedExtraWeights = !expandedExtraWeights },
                expandedContentSpacing = Spacing.sm,
                footerAction = {
                    EquipmentAddButton(
                        onClick = { showExtraWeightDialog.value = true },
                    )
                },
            ) {
                extraWeightsState.value.sortedBy { it.weight }.forEachIndexed { index, plate ->
                    Row(
                        modifier = Modifier.fillMaxWidth().padding(vertical = Spacing.xs),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(stringResource(R.string.equipment_weight_entry, index + 1, plate.weight),
                            style = MaterialTheme.typography.bodyMedium
                        )
                        IconButton(
                            modifier = Modifier.size(32.dp),
                            onClick = {
                                extraWeightsState.value =
                                    extraWeightsState.value - plate
                            }
                        ) {
                            Icon(Icons.Default.Delete, contentDescription = stringResource(R.string.equipment_remove_weight))
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
                        val newDumbbells = Dumbbells(
                            id = dumbbells?.id ?: UUID.randomUUID(),
                            name = nameState.value.trim(),
                            availableDumbbells = availableDumbbellsState.value,
                            extraWeights = extraWeightsState.value,
                            maxExtraWeightsPerLoadingPoint = maxExtraWeightsPerLoadingPointState.value.toIntOrNull() ?: 0,
                        )
                        onUpsert(newDumbbells)
                    },
                    enabled = nameState.value.isNotBlank() && availableDumbbellsState.value.isNotEmpty(),
                    modifier = Modifier.weight(1f)
                )
            }
        }
    }
    // Dialog for adding new dumbbell
    if (showDumbbellDialog.value) {
        StandardDialog(
            onDismissRequest = { showDumbbellDialog.value = false },
            title = stringResource(R.string.equipment_add_dumbbell_pair),
            body = {
                Column {
                    OutlinedTextField(
                        value = newDumbbellWeightState.value,
                        onValueChange = {
                            if (it.isEmpty() || (it.all { it.isDigit() || it == '.' } && !it.startsWith("."))) {
                                newDumbbellWeightState.value = it
                            }
                        },
                        label = { Text(stringResource(R.string.equipment_weight_kg_label)) },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            },
            confirmText = stringResource(R.string.equipment_add),
            onConfirm = {
                val weight = newDumbbellWeightState.value.toDoubleOrNull()
                if (weight != null && weight > 0) {
                    availableDumbbellsState.value += BaseWeight(weight)
                    availableDumbbellsState.value = availableDumbbellsState.value.distinctBy { it.weight }
                    newDumbbellWeightState.value = ""
                    showDumbbellDialog.value = false
                }
            },
            confirmEnabled = newDumbbellWeightState.value.isNotEmpty(),
            dismissText = stringResource(R.string.equipment_cancel),
            onDismissButton = { showDumbbellDialog.value = false }
        )
    }

    // Dialog for adding new additional plate
    if (showExtraWeightDialog.value) {
        StandardDialog(
            onDismissRequest = { showExtraWeightDialog.value = false },
            title = stringResource(R.string.equipment_add_extra_weight),
            body = {
                Column {
                    OutlinedTextField(
                        value = newExtraWeightState.value,
                        onValueChange = {
                            if (it.isEmpty() || (it.all { it.isDigit() || it == '.' } && !it.startsWith("."))) {
                                newExtraWeightState.value = it
                            }
                        },
                        label = { Text(stringResource(R.string.equipment_weight_kg_label)) },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            },
            confirmText = stringResource(R.string.equipment_add),
            onConfirm = {
                val weight = newExtraWeightState.value.toDoubleOrNull()
                if (weight != null && weight > 0) {
                    extraWeightsState.value = extraWeightsState.value + BaseWeight(weight)
                    newExtraWeightState.value = ""
                    showExtraWeightDialog.value = false
                }
            },
            confirmEnabled = newExtraWeightState.value.isNotEmpty(),
            dismissText = stringResource(R.string.equipment_cancel),
            onDismissButton = { showExtraWeightDialog.value = false }
        )
    }
}




