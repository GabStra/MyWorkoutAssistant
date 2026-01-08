package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier

@Composable
fun WorkoutPlanNameDialog(
    show: Boolean,
    initialName: String = "",
    confirmButtonText: String = "Import",
    onDismiss: () -> Unit,
    onConfirm: (String) -> Unit
) {
    if (show) {
        var planName by remember { mutableStateOf(initialName) }
        
        StandardDialog(
            onDismissRequest = onDismiss,
            title = "Enter Workout Plan Name",
            body = {
                OutlinedTextField(
                    value = planName,
                    onValueChange = { planName = it },
                    label = { Text("Plan Name") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true
                )
            },
            confirmText = confirmButtonText,
            onConfirm = {
                if (planName.isNotBlank()) {
                    onConfirm(planName.trim())
                }
            },
            dismissText = "Cancel",
            onDismissButton = onDismiss,
            confirmEnabled = planName.isNotBlank()
        )
    }
}

