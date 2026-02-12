package com.gabstra.myworkoutassistant.screens.equipments

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
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.FormPrimaryButton
import com.gabstra.myworkoutassistant.composables.FormSecondaryButton
import com.gabstra.myworkoutassistant.composables.DialogTextButton
import com.gabstra.myworkoutassistant.shared.DisabledContentGray
import com.gabstra.myworkoutassistant.composables.StandardDialog
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.shared.equipments.BaseWeight
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbell
import com.gabstra.myworkoutassistant.verticalColumnScrollbar
import java.util.UUID

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DumbbellForm(
    onUpsert: (Dumbbell) -> Unit,
    onCancel: () -> Unit,
    dumbbell: Dumbbell? = null,
) {
    // Mutable state for form fields
    val nameState = remember { mutableStateOf(dumbbell?.name ?: "") }
    val maxExtraWeightsPerLoadingPointState = remember { mutableStateOf((dumbbell?.maxExtraWeightsPerLoadingPoint ?: 0).toString()) }

    // State for dumbbells and plates
    val availableDumbbellsState = remember { mutableStateOf(dumbbell?.availableDumbbells ?: emptyList<BaseWeight>()) }
    val extraWeightsState = remember { mutableStateOf(dumbbell?.extraWeights ?: emptyList<BaseWeight>()) }

    // State for new inputs
    val newDumbbellWeightState = remember { mutableStateOf("") }
    val newExtraWeightState = remember { mutableStateOf("") }

    // State for showing dialogs
    val showDumbbellDialog = remember { mutableStateOf(false) }
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
                        text = if(dumbbell == null) "Insert Dumbbell" else "Edit Dumbbell"
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
                .padding(top = 10.dp)
                .padding(bottom = 10.dp)
                .verticalColumnScrollbar(scrollState)
                .verticalScroll(scrollState)
                .padding(horizontal = 15.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            // Dumbbells name field
            OutlinedTextField(
                value = nameState.value,
                onValueChange = { nameState.value = it },
                label = { Text("Dumbbell Set Name") },
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

            // Available Dumbbells Section
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
                            text = "Available Dumbbells",
                            style = MaterialTheme.typography.titleMedium
                        )
                        IconButton(
                            modifier = Modifier.clip(CircleShape)
                                .background(MaterialTheme.colorScheme.primary)
                                .size(35.dp),
                            onClick = { showDumbbellDialog.value = true }
                        ) {
                            Icon(
                                imageVector = Icons.Default.Add,
                                contentDescription = "Add Dumbbell",
                                tint = MaterialTheme.colorScheme.background
                            )
                        }
                    }

                    availableDumbbellsState.value.sortedBy { it.weight }.forEachIndexed { index, dumbbell ->
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = 4.dp),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text("${index+1}) ${dumbbell.weight}kg", style = MaterialTheme.typography.bodyMedium)
                            IconButton(
                                modifier = Modifier.size(35.dp),
                                onClick = {
                                    availableDumbbellsState.value =
                                        availableDumbbellsState.value - dumbbell
                                }
                            ) {
                                Icon(Icons.Default.Delete, contentDescription = "Remove Dumbbell")
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
                        IconButton(
                            modifier = Modifier.clip(CircleShape)
                                .background(MaterialTheme.colorScheme.primary)
                                .size(35.dp),
                            onClick = { showExtraWeightDialog.value = true }
                        ) {
                            Icon(
                                imageVector = Icons.Default.Add,
                                contentDescription = "Add Extra Weight",
                                tint = MaterialTheme.colorScheme.background
                            )
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

            Spacer(Modifier.height(Spacing.xl))

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(Spacing.md),
                verticalAlignment = Alignment.CenterVertically
            ) {
                FormSecondaryButton(
                    text = "Cancel",
                    onClick = {
                        onCancel()
                    },
                    modifier = Modifier.weight(1f)
                )

                FormPrimaryButton(
                    text = "Save",
                    onClick = {
                        val newDumbbell = Dumbbell(
                            id = dumbbell?.id ?: UUID.randomUUID(),
                            name = nameState.value.trim(),
                            availableDumbbells = availableDumbbellsState.value,
                            extraWeights = extraWeightsState.value,
                            maxExtraWeightsPerLoadingPoint = maxExtraWeightsPerLoadingPointState.value.toIntOrNull() ?: 0,
                        )
                        onUpsert(newDumbbell)
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
            title = "Add Dumbbell",
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


