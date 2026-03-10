package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.BorderStroke
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.DisabledContentGray

@Composable
fun StyledCard(
    modifier: Modifier = Modifier,
    borderColor: Color = MaterialTheme.colorScheme.outlineVariant,
    backgroundColor: Color = MaterialTheme.colorScheme.background,
    shape: Shape = MaterialTheme.shapes.medium,
    shadowElevation: Dp = 0.dp,
    enabled: Boolean = true,
    content: @Composable () -> Unit,
) {
    val effectiveBorderColor = if (enabled) {
        borderColor
    } else {
        DisabledContentGray
    }
    
    val effectiveBackgroundColor = if (enabled) {
        backgroundColor
    } else {
        backgroundColor.copy(alpha = 0.6f)
    }
    
    Surface(
        modifier = modifier,
        shape = shape,
        color = effectiveBackgroundColor,
        border = BorderStroke(1.dp, effectiveBorderColor),
        shadowElevation = shadowElevation
    ) {
        content()
    }
}
