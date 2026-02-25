package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import com.gabstra.myworkoutassistant.Spacing

/**
 * Reusable Min/Max row: two numeric fields with decrement/increment stepper buttons.
 * Enforces [minBound]..[maxBound] and min <= max (adjusts the other value when needed).
 *
 * @param minValue Current minimum (integer, e.g. load %, reps, or HR %).
 * @param maxValue Current maximum.
 * @param onMinChange Called when min is changed (already clamped and ordered).
 * @param onMaxChange Called when max is changed (already clamped and ordered).
 * @param minBound Inclusive lower bound for both values.
 * @param maxBound Inclusive upper bound for both values.
 * @param step Increment/decrement amount for stepper buttons (default 1).
 * @param minLabel Label for the minimum field (e.g. "Min").
 * @param maxLabel Label for the maximum field (e.g. "Max").
 */
@Composable
fun MinMaxStepperRow(
    minValue: Int,
    maxValue: Int,
    onMinChange: (Int) -> Unit,
    onMaxChange: (Int) -> Unit,
    minBound: Int,
    maxBound: Int,
    step: Int = 1,
    minLabel: String = "Min",
    maxLabel: String = "Max",
    modifier: Modifier = Modifier
) {
    fun clampAndOrder(newMin: Int, newMax: Int): Pair<Int, Int> {
        val cMin = newMin.coerceIn(minBound, maxBound)
        val cMax = newMax.coerceIn(minBound, maxBound)
        return when {
            cMin > cMax -> cMax to cMax
            cMax < cMin -> cMin to cMin
            else -> cMin to cMax
        }
    }

    var minText by remember { mutableStateOf(minValue.toString()) }
    var maxText by remember { mutableStateOf(maxValue.toString()) }
    androidx.compose.runtime.LaunchedEffect(minValue, maxValue) {
        minText = minValue.toString()
        maxText = maxValue.toString()
    }

    Row(
        modifier = modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(Spacing.md),
        verticalAlignment = Alignment.CenterVertically
    ) {
        // Min column
        Row(
            modifier = Modifier.weight(1f),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(Spacing.xs)
        ) {
            Text(
                text = minLabel,
                style = MaterialTheme.typography.labelMedium,
                modifier = Modifier.width(32.dp)
            )
            IconButton(
                onClick = {
                    val (nMin, nMax) = clampAndOrder(minValue - step, maxValue)
                    onMinChange(nMin)
                    onMaxChange(nMax)
                    minText = nMin.toString()
                    maxText = nMax.toString()
                },
                enabled = minValue > minBound
            ) {
                Icon(
                    imageVector = Icons.Default.KeyboardArrowDown,
                    contentDescription = "Decrease $minLabel"
                )
            }
            OutlinedTextField(
                value = minText,
                onValueChange = { s ->
                    if (s.isEmpty() || s.all { it.isDigit() }) {
                        minText = s
                        val v = s.toIntOrNull()
                        if (v != null) {
                            val (nMin, nMax) = clampAndOrder(v, maxValue)
                            onMinChange(nMin)
                            onMaxChange(nMax)
                            minText = nMin.toString()
                            maxText = nMax.toString()
                        }
                    }
                },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.weight(1f)
            )
            IconButton(
                onClick = {
                    val (nMin, nMax) = clampAndOrder(minValue + step, maxValue)
                    onMinChange(nMin)
                    onMaxChange(nMax)
                    minText = nMin.toString()
                    maxText = nMax.toString()
                },
                enabled = minValue < maxBound && minValue < maxValue
            ) {
                Icon(
                    imageVector = Icons.Default.KeyboardArrowUp,
                    contentDescription = "Increase $minLabel"
                )
            }
        }

        Spacer(Modifier.width(Spacing.sm))

        // Max column
        Row(
            modifier = Modifier.weight(1f),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(Spacing.xs)
        ) {
            Text(
                text = maxLabel,
                style = MaterialTheme.typography.labelMedium,
                modifier = Modifier.width(32.dp)
            )
            IconButton(
                onClick = {
                    val (nMin, nMax) = clampAndOrder(minValue, maxValue - step)
                    onMinChange(nMin)
                    onMaxChange(nMax)
                    minText = nMin.toString()
                    maxText = nMax.toString()
                },
                enabled = maxValue > minBound && maxValue > minValue
            ) {
                Icon(
                    imageVector = Icons.Default.KeyboardArrowDown,
                    contentDescription = "Decrease $maxLabel"
                )
            }
            OutlinedTextField(
                value = maxText,
                onValueChange = { s ->
                    if (s.isEmpty() || s.all { it.isDigit() }) {
                        maxText = s
                        val v = s.toIntOrNull()
                        if (v != null) {
                            val (nMin, nMax) = clampAndOrder(minValue, v)
                            onMinChange(nMin)
                            onMaxChange(nMax)
                            minText = nMin.toString()
                            maxText = nMax.toString()
                        }
                    }
                },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.weight(1f)
            )
            IconButton(
                onClick = {
                    val (nMin, nMax) = clampAndOrder(minValue, maxValue + step)
                    onMinChange(nMin)
                    onMaxChange(nMax)
                    minText = nMin.toString()
                    maxText = nMax.toString()
                },
                enabled = maxValue < maxBound
            ) {
                Icon(
                    imageVector = Icons.Default.KeyboardArrowUp,
                    contentDescription = "Increase $maxLabel"
                )
            }
        }
    }
}
