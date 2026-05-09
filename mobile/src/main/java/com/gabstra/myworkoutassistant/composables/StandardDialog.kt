package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ProvideTextStyle
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties

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
    isConfirmDestructive: Boolean = false,
    maxWidth: Dp = 560.dp,
    usePlatformDefaultWidth: Boolean = true,
    contentHorizontalPadding: Dp = 10.dp,
    contentVerticalPadding: Dp = 10.dp,
) {
    val hasConfirmButton = showConfirm && confirmText != null && onConfirm != null
    val hasDismissButton = showDismiss && dismissText != null

    Dialog(
        onDismissRequest = onDismissRequest,
        properties = DialogProperties(usePlatformDefaultWidth = usePlatformDefaultWidth)
    ) {
        Surface(
            modifier = Modifier
                .fillMaxWidth()
                .widthIn(max = maxWidth),
            shape = MaterialTheme.shapes.small,
            color = MaterialTheme.colorScheme.surfaceContainerHigh,
            tonalElevation = 0.dp
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(
                        horizontal = contentHorizontalPadding,
                        vertical = contentVerticalPadding
                    ),
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
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(max = 480.dp)
                            .verticalScroll(rememberScrollState())
                    ) {
                        body()
                    }
                }

                if (hasConfirmButton || hasDismissButton) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.End)
                    ){
                        if (hasDismissButton) {
                            DialogOutlinedButton(
                                text = dismissText.orEmpty(),
                                onClick = onDismissButton ?: onDismissRequest,
                                modifier = Modifier.heightIn(min = 48.dp),
                                minHeight = 48.dp
                            )
                        }
                        if (hasConfirmButton) {
                            val confirmLabel = requireNotNull(confirmText)
                            val confirmAction = requireNotNull(onConfirm)
                            if (isConfirmDestructive) {
                                if (confirmLabel.equals("Delete", ignoreCase = true)) {
                                    AppDeleteButton(
                                        text = confirmLabel,
                                        onClick = confirmAction,
                                        enabled = confirmEnabled,
                                        modifier = Modifier.heightIn(min = 48.dp),
                                        minHeight = 48.dp
                                    )
                                } else {
                                    AppDestructiveButton(
                                        text = confirmLabel,
                                        onClick = confirmAction,
                                        enabled = confirmEnabled,
                                        modifier = Modifier.heightIn(min = 48.dp),
                                        minHeight = 48.dp
                                    )
                                }
                            } else {
                                AppPrimaryButton(
                                    text = confirmLabel,
                                    onClick = confirmAction,
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
}
