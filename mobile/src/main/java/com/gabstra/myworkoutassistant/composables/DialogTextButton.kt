package com.gabstra.myworkoutassistant.composables

import androidx.compose.runtime.Composable
import androidx.compose.ui.unit.dp

@Composable
fun DialogTextButton(
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

