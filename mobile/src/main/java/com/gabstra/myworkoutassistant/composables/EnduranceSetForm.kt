package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.DarkGray
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.LightGray
import java.util.UUID

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EnduranceSetForm(
    onSetUpsert: (Set) -> Unit,
    enduranceSet: EnduranceSet? = null,
) {

    val autoStartState = remember { mutableStateOf(enduranceSet?.autoStart ?: false) }
    val autoStopState = remember { mutableStateOf(enduranceSet?.autoStop ?: false) }

    val hms = remember { mutableStateOf(TimeConverter.secondsToHms(enduranceSet?.timeInMillis?.div(1000) ?: 0)) }
    val (hours, minutes, seconds) = hms.value

    Column(
        modifier = Modifier
            .fillMaxWidth()
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp),
        ) {
            Text("Duration", color = LightGray)
            Spacer(modifier = Modifier.height(15.dp))
            CustomTimePicker(
                initialHour = hours,
                initialMinute = minutes,
                initialSecond = seconds,
                onTimeChange = { hour, minute, second ->
                    hms.value = Triple(hour, minute, second)
                }
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
                colors = CheckboxDefaults.colors().copy(
                    checkedCheckmarkColor = MaterialTheme.colorScheme.onPrimary,
                    uncheckedBorderColor = MaterialTheme.colorScheme.primary
                )
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
                colors = CheckboxDefaults.colors().copy(
                    checkedCheckmarkColor = MaterialTheme.colorScheme.onPrimary,
                    uncheckedBorderColor = MaterialTheme.colorScheme.primary
                )
            )
            Text(text = "Auto stop")
        }

        // Submit button
        Button(
            colors = ButtonDefaults.buttonColors(contentColor = MaterialTheme.colorScheme.background),
            onClick = {

                val newEnduranceSet = EnduranceSet(
                    id = UUID.randomUUID(),
                    timeInMillis = TimeConverter.hmsTotalSeconds(hours, minutes, seconds)* 1000,
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
            if (enduranceSet == null) Text("Insert Count-Up Set", color = DarkGray) else Text("Edit Count-Up Set", color = DarkGray)
        }
    }
}
