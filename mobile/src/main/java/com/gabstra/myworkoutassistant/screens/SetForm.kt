package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.composables.BodyWeightSetForm
import com.gabstra.myworkoutassistant.composables.EnduranceSetForm
import com.gabstra.myworkoutassistant.composables.TimedDurationSetForm
import com.gabstra.myworkoutassistant.composables.WeightSetForm
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet

enum class SetType {
    COUNTUP_SET, BODY_WEIGHT_SET, COUNTDOWN_SET, WEIGHT_SET
}

fun SetType.toReadableString(): String {
    return this.name.replace('_', ' ').split(' ').joinToString(" ") { it.capitalize() }
}

fun getSetTypeDescriptions(): List<String> {
    return SetType.values().map { it.toReadableString() }
}

fun stringToSetType(value: String): SetType? {
    return SetType.values().firstOrNull {
        it.name.equals(value.replace(' ', '_').toUpperCase(), ignoreCase = true)
    }
}

fun getSetTypeFromSet(set: Set): SetType {
    return when (set) {
        is WeightSet -> SetType.WEIGHT_SET
        is BodyWeightSet -> SetType.BODY_WEIGHT_SET
        is EnduranceSet -> SetType.COUNTUP_SET
        is TimedDurationSet -> SetType.COUNTDOWN_SET
    }
}

@Composable
fun SetForm(
    onSetUpsert: (Set) -> Unit,
    onCancel: () -> Unit,
    set: Set? = null // Add exercise parameter with default value null
) {
    val selectedSetType = remember { mutableStateOf(if(set!=null) getSetTypeFromSet(set) else SetType.WEIGHT_SET) }
    val setTypeDescriptions = getSetTypeDescriptions()
    val expanded = remember { mutableStateOf(false) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.Center,
    ){
        if(set == null){
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp)
            ) {
                Text(text = "Set Type:")
                Box(modifier = Modifier.fillMaxWidth()) {
                    Text(
                        text = selectedSetType.value.name.replace('_', ' ').capitalize(),
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { expanded.value = true }
                            .padding(8.dp)
                    )
                    DropdownMenu(
                        expanded = expanded.value,
                        onDismissRequest = { expanded.value = false },
                    ) {
                        setTypeDescriptions.forEach { setDescription ->
                            DropdownMenuItem(
                                onClick = {
                                    selectedSetType.value = stringToSetType(setDescription)!!
                                    expanded.value = false
                                },
                                text = {
                                    Text(text = setDescription)
                                }
                            )
                        }
                    }
                }
            }
            Spacer(modifier = Modifier.height(10.dp))
        }

        when (selectedSetType.value) {
            SetType.WEIGHT_SET -> {
                WeightSetForm(
                    onSetUpsert = onSetUpsert,
                    weightSet = set as WeightSet?
                )
            }
            SetType.BODY_WEIGHT_SET -> {
                BodyWeightSetForm(
                    onSetUpsert = onSetUpsert,
                    bodyWeightSet = set as BodyWeightSet?
                )
            }
            SetType.COUNTUP_SET -> {
                EnduranceSetForm(
                    onSetUpsert = onSetUpsert,
                    enduranceSet = set as EnduranceSet?
                )
            }
            SetType.COUNTDOWN_SET -> {
                TimedDurationSetForm(
                    onSetUpsert = onSetUpsert,
                    timedDurationSet = set as TimedDurationSet?
                )
            }
        }

        Button(
            onClick = {
                onCancel()
            },
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp)
        ) {
            Text("Cancel")
        }
    }
}