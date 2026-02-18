package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ProvideTextStyle
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import com.gabstra.myworkoutassistant.shared.DarkGray

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
    val hasConfirmButton = showConfirm && confirmText != null && onConfirm != null
    val hasDismissButton = showDismiss && dismissText != null

    Dialog(onDismissRequest = onDismissRequest) {
        Surface(
            modifier = Modifier
                .fillMaxWidth()
                .widthIn(max = 560.dp),
            shape = MaterialTheme.shapes.small,
            color = DarkGray,
            tonalElevation = 0.dp
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 24.dp, vertical = 20.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                when {
                    titleContent != null -> titleContent()
                    title != null -> Text(
                        text = title,
                        style = MaterialTheme.typography.titleMedium,
                        color = MaterialTheme.colorScheme.onSurface
                    )
                }

                ProvideTextStyle(
                    value = MaterialTheme.typography.bodyMedium.copy(
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                ) {
                    Box(modifier = Modifier.fillMaxWidth()) {
                        body()
                    }
                }

                if (hasConfirmButton || hasDismissButton) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.End)
                    ){
                        if (hasDismissButton) {
                            AppSecondaryButton(
                                text = dismissText!!,
                                onClick = onDismissButton ?: onDismissRequest,
                                modifier = Modifier.heightIn(min = 48.dp),
                                minHeight = 48.dp
                            )
                        }
                        if (hasConfirmButton) {
                            AppPrimaryButton(
                                text = confirmText!!,
                                onClick = onConfirm!!,
                                enabled = confirmEnabled,
                                modifier = Modifier.heightIn(min = 48.dp),
                                minHeight = 48.dp
                            )
                        }
                    }
                }
            }
        }
    }
}
