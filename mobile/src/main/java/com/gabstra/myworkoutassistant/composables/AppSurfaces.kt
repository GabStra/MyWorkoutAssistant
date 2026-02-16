package com.gabstra.myworkoutassistant.composables

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.material3.MaterialTheme

@Composable
fun PrimarySurface(
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    backgroundColor: Color = MaterialTheme.colorScheme.background,
    content: @Composable () -> Unit
) {
    StyledCard(
        modifier = modifier,
        backgroundColor = backgroundColor,
        borderColor = MaterialTheme.colorScheme.outlineVariant,
        shape = MaterialTheme.shapes.medium,
        shadowElevation = 2.dp,
        enabled = enabled,
        content = content
    )
}

@Composable
fun SecondarySurface(
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    backgroundColor: Color = MaterialTheme.colorScheme.surfaceVariant,
    content: @Composable () -> Unit
) {
    StyledCard(
        modifier = modifier,
        backgroundColor = backgroundColor,
        borderColor = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.8f),
        shape = MaterialTheme.shapes.small,
        shadowElevation = 0.dp,
        enabled = enabled,
        content = content
    )
}
