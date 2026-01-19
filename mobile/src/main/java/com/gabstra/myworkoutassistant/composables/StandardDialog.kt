package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ProvideTextStyle
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.DarkGray
import com.gabstra.myworkoutassistant.shared.DisabledContentGray

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
                Button(
                    onClick = onConfirm,
                    enabled = confirmEnabled,
                    modifier = Modifier.heightIn(min = 48.dp),
                    colors = ButtonDefaults.buttonColors(
                        contentColor = MaterialTheme.colorScheme.background,
                        disabledContentColor = DisabledContentGray
                    )
                ) {
                    Text(
                        text = confirmText,
                        color = MaterialTheme.colorScheme.onPrimary,
                        style = MaterialTheme.typography.bodyLarge
                    )
                }
            }
        },
        dismissButton = {
            if (showDismiss && dismissText != null) {
                CustomButton(
                    text = dismissText,
                    onClick = onDismissButton ?: onDismissRequest,
                    modifier = Modifier.heightIn(min = 48.dp)
                )
            }
        },
        shape = RoundedCornerShape(4.dp),
        containerColor = DarkGray,
        titleContentColor = MaterialTheme.colorScheme.onSurface,
        textContentColor = MaterialTheme.colorScheme.onSurfaceVariant,
        tonalElevation = 0.dp,
    )
}


