package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.background
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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.composables.CustomTimePicker
import com.gabstra.myworkoutassistant.composables.TimeConverter
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RestForm(
    onRestUpsert: (Rest) -> Unit,
    onCancel: () -> Unit,
    rest: Rest? = null, // Add exercise parameter with default value null
) {
    val hms = remember { mutableStateOf(TimeConverter.secondsToHms(rest?.timeInSeconds ?: 0)) }
    val (hours, minutes, seconds) = hms.value

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.Center,
    ) {

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp),
        ) {
            Text("Rest Time Between Exercises")
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

        // Submit button
        Button(
            colors = ButtonDefaults.buttonColors(contentColor = MaterialTheme.colorScheme.background),
            onClick = {
                val newRest = Rest(
                    id = rest?.id ?: java.util.UUID.randomUUID(),
                    enabled = rest?.enabled ?: true,
                    timeInSeconds = TimeConverter.hmsTotalSeconds(hours, minutes, seconds),
                )

                onRestUpsert(newRest)
            },
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp),
        ) {
            if (rest == null) Text("Insert Rest") else Text("Edit Rest")
        }

        // Cancel button
        Button(
            colors = ButtonDefaults.buttonColors(contentColor = MaterialTheme.colorScheme.background),
            onClick = {
                // Call the callback to cancel the insertion/update
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