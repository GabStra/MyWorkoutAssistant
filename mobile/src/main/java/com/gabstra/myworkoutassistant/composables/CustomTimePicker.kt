package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp

object TimeConverter {
    /**
     * Converts hours, minutes, and seconds to total seconds.
     *
     * @param hours The number of hours.
     * @param minutes The number of minutes.
     * @param seconds The number of seconds.
     * @return The total number of seconds.
     */
    fun hmsToTotalSeconds(hours: Int, minutes: Int, seconds: Int): Int {
        return hours * 3600 + minutes * 60 + seconds
    }

    /**
     * Converts total seconds to hours, minutes, and seconds.
     *
     * @param totalSeconds The total number of seconds.
     * @return A Triple containing hours, minutes, and seconds.
     */
    fun secondsToHms(totalSeconds: Int): Triple<Int, Int, Int> {
        if (totalSeconds == 0) {
            return Triple(0, 0, 0)
        }

        val hours = totalSeconds / 3600
        val minutes = (totalSeconds % 3600) / 60
        val seconds = totalSeconds % 60
        return Triple(hours, minutes, seconds)
    }
}

@Composable
fun CustomTimePicker(
    modifier: Modifier = Modifier.fillMaxWidth(),
    initialHour: Int = 0,
    initialMinute: Int = 0,
    initialSecond: Int = 0,
    onTimeChange: (hour: Int, minute: Int, second: Int) -> Unit
) {
    var hour by remember { mutableStateOf(initialHour.toString().padStart(2, '0')) }
    var minute by remember { mutableStateOf(initialMinute.toString().padStart(2, '0')) }
    var second by remember { mutableStateOf(initialSecond.toString().padStart(2, '0')) }

    fun updateTime() {
        val h = hour.toIntOrNull() ?: 0
        val m = minute.toIntOrNull() ?: 0
        val s = second.toIntOrNull() ?: 0
        onTimeChange(h, m, s)
    }

    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically
    ) {
        TimeInputField(
            value = hour,
            onValueChange = { newValue ->
                val parsed = newValue.toIntOrNull()
                if (newValue.isEmpty() || (parsed != null && parsed in 0..23)) {
                    hour = newValue.take(2)
                    updateTime()
                }
            },
            label = "Hour"
        )
        Text(":", style = MaterialTheme.typography.headlineMedium)
        TimeInputField(
            value = minute,
            onValueChange = { newValue ->
                val parsed = newValue.toIntOrNull()
                if (newValue.isEmpty() || (parsed != null && parsed in 0..59)) {
                    minute = newValue.take(2)
                    updateTime()
                }
            },
            label = "Minute"
        )
        Text(":", style = MaterialTheme.typography.headlineMedium)
        TimeInputField(
            value = second,
            onValueChange = { newValue ->
                val parsed = newValue.toIntOrNull()
                if (newValue.isEmpty() || (parsed != null && parsed in 0..59)) {
                    second = newValue.take(2)
                    updateTime()
                }
            },
            label = "Second"
        )
    }
}

@Composable
fun TimeInputField(
    value: String,
    onValueChange: (String) -> Unit,
    label: String
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        label = { Text(text = label, style = MaterialTheme.typography.bodySmall) },
        singleLine = true,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
        modifier = Modifier.width(80.dp)
    )
}

