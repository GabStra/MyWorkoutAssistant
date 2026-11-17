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
import androidx.compose.ui.res.stringResource
import com.gabstra.myworkoutassistant.R

@Composable
fun WorkoutPlanNameDialog(
    show: Boolean,
    initialName: String = "",
    confirmButtonText: String = stringResource(R.string.dialog_import),
    onDismiss: () -> Unit,
    onConfirm: (String) -> Unit
) {
    if (show) {
        var planName by remember { mutableStateOf(initialName) }
        
        StandardDialog(
            onDismissRequest = onDismiss,
            title = stringResource(R.string.dialog_enter_plan_name_title),
            body = {
                OutlinedTextField(
                    value = planName,
                    onValueChange = { planName = it },
                    label = { Text(stringResource(R.string.dialog_plan_name_label)) },
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
            dismissText = stringResource(R.string.common_cancel),
            onDismissButton = onDismiss,
            confirmEnabled = planName.isNotBlank()
        )
    }
}

