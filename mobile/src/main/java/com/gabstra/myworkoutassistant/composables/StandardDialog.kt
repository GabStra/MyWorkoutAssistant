package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ProvideTextStyle
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.unit.dp

@Composable
fun StandardDialog(
    onDismissRequest: () -> Unit,
    title: String? = null,
    titleContent: (@Composable () -> Unit)? = null,
    body: @Composable () -> Unit,
    confirmText: String? = null,
    onConfirm: (() -> Unit)? = null,
    dismissText: String? = null,
    onDismissButton: (() -> Unit)? = null,
    showConfirm: Boolean = true,
    showDismiss: Boolean = true,
    confirmEnabled: Boolean = true,
) {
    AlertDialog(
        onDismissRequest = onDismissRequest,
        title = {
            when {
                titleContent != null -> titleContent()
                title != null -> Text(
                    text = title,
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onSurface
                )
            }
        },
        text = {
            ProvideTextStyle(
                value = MaterialTheme.typography.bodyMedium.copy(
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            ) {
                body()
            }
        },
        confirmButton = {
            if (showConfirm && confirmText != null && onConfirm != null) {
                DialogTextButton(
                    text = confirmText,
                    onClick = onConfirm,
                    enabled = confirmEnabled
                )
            }
        },
        dismissButton = {
            if (showDismiss && dismissText != null) {
                DialogTextButton(
                    text = dismissText,
                    onClick = onDismissButton ?: onDismissRequest
                )
            }
        },
        shape = RoundedCornerShape(4.dp),
        containerColor = MaterialTheme.colorScheme.surface,
        titleContentColor = MaterialTheme.colorScheme.onSurface,
        textContentColor = MaterialTheme.colorScheme.onSurfaceVariant,
        tonalElevation = 0.dp,
    )
}


