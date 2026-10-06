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
                        text = if (dumbbells == null) "Insert Dumbbell Pair" else "Edit Dumbbell Pair"
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
                    IconButton(modifier = Modifier.alpha(0f), onClick = { onCancel() }) {
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
                .padding(vertical = Spacing.sm)
                .verticalScroll(scrollState)
                .padding(horizontal = Spacing.md),
            verticalArrangement = Arrangement.spacedBy(Spacing.sm)
        ) {
            EquipmentFormSection(title = "Details") {
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    verticalArrangement = Arrangement.spacedBy(Spacing.sm)
                ) {
                    OutlinedTextField(
                        value = nameState.value,
                        onValueChange = { nameState.value = it },
                        label = { Text("Name", style = MaterialTheme.typography.labelLarge) },
                        modifier = Modifier.fillMaxWidth()
                    )
                    OutlinedTextField(
                        value = maxExtraWeightsPerLoadingPointState.value,
                        onValueChange = {
                            if (it.isEmpty() || it.all { char -> char.isDigit() }) {
                                maxExtraWeightsPerLoadingPointState.value = it
                            }
                        },
                        label = { Text("Maximum Additional Plates", style = MaterialTheme.typography.labelLarge) },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            }

            CollapsibleSection(
                title = "Available Dumbbell Pairs",
                summary = "${availableDumbbellsState.value.size} pair${if (availableDumbbellsState.value.size == 1) "" else "s"}",
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
                        Text("${index+1}) ${dumbbell.weight}kg", style = MaterialTheme.typography.bodyMedium)
                        IconButton(
                            modifier = Modifier.size(32.dp),
                            onClick = {
                                availableDumbbellsState.value =
                                    availableDumbbellsState.value - dumbbell
                            }
                        ) {
                            Icon(Icons.Default.Delete, contentDescription = "Remove dumbbell pair")
                        }
                    }
                }
            }

            CollapsibleSection(
                title = "Extra Weights",
                summary = "${extraWeightsState.value.size} weights",
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
                        Text("${index+1}) ${plate.weight}kg",
                            style = MaterialTheme.typography.bodyMedium
                        )
                        IconButton(
                            modifier = Modifier.size(32.dp),
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

            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = Spacing.sm),
                horizontalArrangement = Arrangement.spacedBy(Spacing.md),
                verticalAlignment = Alignment.CenterVertically
            ) {
                AppSecondaryButton(
                    text = "Cancel",
                    onClick = {
                        onCancel()
                    },
                    modifier = Modifier.weight(1f)
                )

                AppPrimaryButton(
                    text = "Save",
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
            title = "Add Dumbbell Pair",
            body = {
                Column {
                    OutlinedTextField(
                        value = newDumbbellWeightState.value,
                        onValueChange = {
                            if (it.isEmpty() || (it.all { it.isDigit() || it == '.' } && !it.startsWith("."))) {
                                newDumbbellWeightState.value = it
                            }
                        },
                        label = { Text("Weight (KG)") },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            },
            confirmText = "Add",
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
            dismissText = "Cancel",
            onDismissButton = { showDumbbellDialog.value = false }
        )
    }

    // Dialog for adding new additional plate
    if (showExtraWeightDialog.value) {
        StandardDialog(
            onDismissRequest = { showExtraWeightDialog.value = false },
            title = "Add Extra Weight",
            body = {
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
            confirmText = "Add",
            onConfirm = {
                val weight = newExtraWeightState.value.toDoubleOrNull()
                if (weight != null && weight > 0) {
                    extraWeightsState.value = extraWeightsState.value + BaseWeight(weight)
                    newExtraWeightState.value = ""
                    showExtraWeightDialog.value = false
                }
            },
            confirmEnabled = newExtraWeightState.value.isNotEmpty(),
            dismissText = "Cancel",
            onDismissButton = { showExtraWeightDialog.value = false }
        )
    }
}




