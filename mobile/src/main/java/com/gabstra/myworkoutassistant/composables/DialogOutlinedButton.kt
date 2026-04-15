package com.gabstra.myworkoutassistant.composables

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/** Compact outlined control for dialog action rows (not a [androidx.compose.material3.TextButton]). */
@Composable
fun DialogOutlinedButton(
    modifier: Modifier = Modifier,
    text: String,
    onClick: () -> Unit,
    enabled: Boolean = true,
    minHeight: Dp = 32.dp
) {
    AppPrimaryOutlinedButton(
        modifier = modifier,
        text = text,
        onClick = onClick,
        enabled = enabled,
        minHeight = minHeight
    )
}
