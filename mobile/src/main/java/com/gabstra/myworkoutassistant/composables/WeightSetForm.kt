package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import java.util.UUID

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WeightSetForm(
    onSetUpsert: (Set) -> Unit,
    weightSet: WeightSet? = null // Add exercise parameter with default value null
) {
    // Mutable state for form fields
    val repsState = remember { mutableStateOf(weightSet?.reps?.toString() ?: "") }
    val weightState = remember { mutableStateOf(weightSet?.weight?.toString() ?: "") }

    Column(
        modifier = Modifier
            .fillMaxWidth()
    ) {
        // Reps field
        OutlinedTextField(
            value = repsState.value,
            onValueChange = { input ->
                if (input.isEmpty() || input.all { it -> it.isDigit() }) {
                    // Update the state only if the input is empty or all characters are digits
                    repsState.value = input
                }
            },
            label = { Text("Repetitions") },
            keyboardOptions = KeyboardOptions.Default.copy(keyboardType = KeyboardType.Number),
            modifier = Modifier
                .fillMaxWidth()
        )

        // Weight field
        OutlinedTextField(
            value = weightState.value,
            onValueChange = { input ->
                if (input.isEmpty() || (input.all { it.isDigit() || it == '.' } && !input.startsWith("."))) {
                    // Update the state only if the input is empty or all characters are digits
                    weightState.value = input
                }
            },
            label = { Text("Weight (kg)") },
            keyboardOptions = KeyboardOptions.Default.copy(keyboardType = KeyboardType.Number),
            modifier = Modifier
                .fillMaxWidth()
        )

        // Submit button
        Button(
            colors = ButtonDefaults.buttonColors(contentColor = MaterialTheme.colorScheme.background),
            onClick = {
                val reps = repsState.value.toIntOrNull() ?: 0
                val weight = weightState.value.toFloatOrNull() ?: 0f
                val newWeightSet = WeightSet(
                    id = UUID.randomUUID(),
                    reps = if (reps >= 0) reps else 0,
                    weight = if (weight >= 0f) weight else 0f,
                )

                // Call the callback to insert/update the exercise
                onSetUpsert(newWeightSet)
            },
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp)
        ) {
            if (weightSet == null) Text("Insert Weight Set") else Text("Edit Weight Set")
        }
    }
}
