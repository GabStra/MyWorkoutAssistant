package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.equipments.CardioMachine
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

@Composable
fun TimedSetLoadField(
    equipment: WeightLoadedEquipment?,
    selectedWeight: Double?,
    onWeightSelected: (Double?) -> Unit,
) {
    if (equipment == null || equipment is CardioMachine) return

    var combinations by remember(equipment.id) {
        mutableStateOf<Set<Pair<Double, String>>>(emptySet())
    }
    var loading by remember(equipment.id) { mutableStateOf(true) }
    var pickerVisible by remember { mutableStateOf(false) }
    var filter by remember { mutableStateOf("") }

    LaunchedEffect(equipment.id) {
        combinations = withContext(Dispatchers.IO) {
            equipment.getWeightsCombinationsWithLabels()
        }
        loading = false
    }

    Box(modifier = Modifier.fillMaxWidth()) {
        OutlinedTextField(
            value = selectedWeight?.let(equipment::formatWeight) ?: "Not set",
            onValueChange = {},
            readOnly = true,
            enabled = !loading,
            label = { Text("Target load") },
            modifier = Modifier.fillMaxWidth().padding(8.dp),
        )
        Box(
            modifier = Modifier
                .matchParentSize()
                .clickable(enabled = !loading) { pickerVisible = true },
        )
        if (loading) {
            CircularProgressIndicator(
                modifier = Modifier
                    .align(Alignment.CenterEnd)
                    .padding(end = 24.dp),
            )
        }
    }

    if (selectedWeight != null) {
        TextButton(onClick = { onWeightSelected(null) }) {
            Text("Remove target load")
        }
    }

    if (pickerVisible) {
        WeightPickerDialog(
            combinations = combinations
                .filter { (_, label) -> label.contains(filter, ignoreCase = true) }
                .sortedBy { it.first },
            filter = filter,
            selectedWeight = selectedWeight ?: 0.0,
            onFilterChange = { filter = it },
            onDismissRequest = { pickerVisible = false },
            onSelect = {
                onWeightSelected(it)
                pickerVisible = false
            },
        )
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun TimedSetExecutionLoadLabel(
    equipment: WeightLoadedEquipment?,
    selectedWeight: Double?,
    editable: Boolean,
    onWeightSelected: (Double) -> Unit,
) {
    if (equipment == null || equipment is CardioMachine || selectedWeight == null) return

    var combinations by remember(equipment.id) {
        mutableStateOf<Set<Pair<Double, String>>>(emptySet())
    }
    var pickerVisible by remember { mutableStateOf(false) }
    var filter by remember { mutableStateOf("") }

    LaunchedEffect(equipment.id) {
        combinations = withContext(Dispatchers.IO) {
            equipment.getWeightsCombinationsWithLabels()
        }
    }

    Text(
        text = "Load ${equipment.formatWeight(selectedWeight)}",
        style = MaterialTheme.typography.labelMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.combinedClickable(
            onClick = {},
            onLongClick = { if (editable && combinations.isNotEmpty()) pickerVisible = true },
        ),
    )

    if (pickerVisible) {
        WeightPickerDialog(
            combinations = combinations
                .filter { (_, label) -> label.contains(filter, ignoreCase = true) }
                .sortedBy { it.first },
            filter = filter,
            selectedWeight = selectedWeight,
            onFilterChange = { filter = it },
            onDismissRequest = { pickerVisible = false },
            onSelect = {
                onWeightSelected(it)
                pickerVisible = false
            },
        )
    }
}
