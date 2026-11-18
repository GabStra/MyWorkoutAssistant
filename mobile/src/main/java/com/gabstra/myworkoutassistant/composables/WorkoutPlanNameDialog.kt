package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.shared.isReservedWorkoutPlanName

/** True when [rawName], after the dialog's trimming, is the reserved legacy plan name. */
internal fun isReservedPlanNameInput(rawName: String): Boolean =
    isReservedWorkoutPlanName(rawName.trim())

@Composable
fun WorkoutPlanNameDialog(
    show: Boolean,
    initialName: String = "",
    confirmButtonText: String = stringResource(R.string.dialog_import),
    errorMessage: String? = null,
    onDismiss: () -> Unit,
    onConfirm: (String) -> Unit
) {
    if (show) {
        var planName by remember { mutableStateOf(initialName) }
        val isReservedName = isReservedPlanNameInput(planName)
        
        StandardDialog(
            onDismissRequest = onDismiss,
            title = stringResource(R.string.dialog_enter_plan_name_title),
            body = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = planName,
                        onValueChange = { planName = it },
                        label = { Text(stringResource(R.string.dialog_plan_name_label)) },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                        isError = isReservedName,
                        supportingText = if (isReservedName) {
                            { Text(stringResource(R.string.loc_plan_name_reserved)) }
                        } else {
                            null
                        },
                    )
                    if (errorMessage != null) {
                        Text(
                            text = errorMessage,
                            color = MaterialTheme.colorScheme.error,
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                }
            },
            confirmText = confirmButtonText,
            onConfirm = {
                if (planName.isNotBlank() && !isReservedName) {
                    onConfirm(planName.trim())
                }
            },
            dismissText = stringResource(R.string.common_cancel),
            onDismissButton = onDismiss,
            confirmEnabled = planName.isNotBlank() && !isReservedName,
        )
    }
}

