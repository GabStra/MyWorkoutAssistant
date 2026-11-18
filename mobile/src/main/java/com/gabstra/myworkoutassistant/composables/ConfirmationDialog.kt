package com.gabstra.myworkoutassistant.composables

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.gabstra.myworkoutassistant.R

@Composable
fun ConfirmationDialog(
    show: Boolean,
    title: String,
    message: String,
    confirmText: String = stringResource(R.string.loc_confirm),
    dismissText: String = stringResource(R.string.common_cancel),
    isDestructive: Boolean = false,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    if (!show) return

    StandardDialog(
        onDismissRequest = onDismiss,
        title = title,
        body = {
            Text(
                text = message,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        },
        confirmText = confirmText,
        onConfirm = onConfirm,
        dismissText = dismissText,
        onDismissButton = onDismiss,
        isConfirmDestructive = isDestructive
    )
}
