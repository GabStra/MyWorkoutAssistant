package com.gabstra.myworkoutassistant.composables

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable

@Composable
fun ConfirmationDialog(
    show: Boolean,
    title: String,
    message: String,
    confirmText: String = "Confirm",
    dismissText: String = "Cancel",
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
