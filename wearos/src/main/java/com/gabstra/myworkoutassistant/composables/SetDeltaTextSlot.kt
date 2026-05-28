package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.height
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme

@Composable
fun SetDeltaTextSlot(
    deltaText: String?,
    color: androidx.compose.ui.graphics.Color,
    modifier: Modifier = Modifier,
) {
    Box(
        modifier = modifier.height(16.dp),
        contentAlignment = Alignment.TopCenter,
    ) {
        if (deltaText != null) {
            ScalableText(
                text = deltaText,
                style = MaterialTheme.typography.bodySmall,
                color = color,
                textAlign = TextAlign.Center,
            )
        }
    }
}
