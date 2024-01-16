package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.formatMillisecondsToMinutesSeconds
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.Set

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EnduranceSetForm(
    onSetUpsert: (Set) -> Unit,
    enduranceSet: EnduranceSet? = null // Add exercise parameter with default value null
) {
    // Mutable state for form fields
    val timeInSecondsState = remember { mutableStateOf(enduranceSet?.timeInMillis?.div(1000)?.toString() ?: "") }
    val autoStartState = remember { mutableStateOf(enduranceSet?.autoStart ?: false) }
    val autoStopState = remember { mutableStateOf(enduranceSet?.autoStop ?: false) }

    Column(
        modifier = Modifier
            .fillMaxWidth()
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp),
        ) {
            if(timeInSecondsState.value.isNotEmpty()){
                Text(formatMillisecondsToMinutesSeconds(timeInSecondsState.value.toInt()))
                Spacer(modifier = Modifier.height(15.dp))
            }
            // Rest time field
            OutlinedTextField(
                value = timeInSecondsState.value,
                onValueChange = { input ->
                    if (input.isEmpty() || (input.all { it.isDigit() || it == '.' } && !input.startsWith("."))) {
                        // Update the state only if the input is empty or all characters are digits
                        timeInSecondsState.value = input
                    }
                },
                label = { Text("Duration (in seconds)") },
                keyboardOptions = KeyboardOptions.Default.copy(keyboardType = KeyboardType.Number),
                modifier = Modifier
                    .fillMaxWidth()
            )
        }

        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp)
        ) {
            Checkbox(
                checked = autoStartState.value,
                onCheckedChange = { autoStartState.value = it },
            )
            Text(text = "Auto start")
        }

        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp)
        ) {
            Checkbox(
                checked = autoStopState.value,
                onCheckedChange = { autoStopState.value = it },
            )
            Text(text = "Auto stop")
        }

        // Submit button
        Button(
            onClick = {
                val timeInSeconds = timeInSecondsState.value.toIntOrNull() ?: 0
                val newEnduranceSet = EnduranceSet(
                    timeInMillis = if (timeInSeconds >= 0) timeInSeconds * 1000 else 0,
                    autoStart = autoStartState.value,
                    autoStop = autoStopState.value,
                )

                // Call the callback to insert/update the exercise
                onSetUpsert(newEnduranceSet)
            },
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp)
        ) {
            if (enduranceSet == null) Text("Insert CountUp Set") else Text("Edit CountUp Set")
        }
    }
}
