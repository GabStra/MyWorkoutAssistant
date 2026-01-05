package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.runtime.Composable
import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

@Composable
fun StyledCard(
    modifier: Modifier = Modifier,
    borderColor : Color = MaterialTheme.colorScheme.outlineVariant,
    backgroundColor: Color = MaterialTheme.colorScheme.background,
    enabled: Boolean = true,
    content: @Composable () -> Unit,
) {
    val effectiveBorderColor = if (enabled) {
        borderColor
    } else {
        MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.38f)
    }
    
    val effectiveBackgroundColor = if (enabled) {
        backgroundColor
    } else {
        backgroundColor.copy(alpha = 0.6f)
    }
    
    Box(
        modifier = modifier
            .border(1.dp, effectiveBorderColor)
            .background(effectiveBackgroundColor)
            .wrapContentSize(),
        contentAlignment = Alignment.Center,
    ) {
        content()
    }
}
