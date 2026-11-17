package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.R

@Composable
fun EditPlanNameDialog(
    show: Boolean,
    currentName: String,
    suggestNextPrescription: Boolean = true,
    onDismiss: () -> Unit,
    onConfirm: (String, Boolean) -> Unit
) {
    if (show) {
        var planName by remember(currentName) { mutableStateOf(currentName) }
        var suggestNext by remember(currentName, suggestNextPrescription) { mutableStateOf(suggestNextPrescription) }
        
        StandardDialog(
            onDismissRequest = onDismiss,
            title = stringResource(R.string.dialog_plan_settings_title),
            body = {
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    OutlinedTextField(
                        value = planName,
                        onValueChange = { planName = it },
                        label = { Text(stringResource(R.string.dialog_plan_name_label)) },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true
                    )
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
                    ) {
                        Text(
                            text = stringResource(R.string.dialog_suggest_next_prescription),
                            modifier = Modifier.weight(1f),
                        )
                        Switch(
                            modifier = Modifier.testTag("suggest_next_prescription_toggle"),
                            checked = suggestNext,
                            onCheckedChange = { suggestNext = it },
                        )
                    }
                }
            },
            confirmText = stringResource(R.string.common_save),
            onConfirm = {
                if (planName.isNotBlank()) {
                    onConfirm(planName.trim(), suggestNext)
                }
            },
            dismissText = stringResource(R.string.common_cancel),
            onDismissButton = onDismiss,
            confirmEnabled = planName.isNotBlank()
        )
    }
}

