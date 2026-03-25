package com.gabstra.myworkoutassistant.composables

import androidx.compose.runtime.Composable
import androidx.compose.ui.unit.dp

/** Compact outlined control for dialog action rows (not a [androidx.compose.material3.TextButton]). */
@Composable
fun DialogOutlinedButton(
    text: String,
    onClick: () -> Unit,
    enabled: Boolean = true
) {
    AppPrimaryOutlinedButton(
        text = text,
        onClick = onClick,
        enabled = enabled,
        minHeight = 32.dp
    )
}
