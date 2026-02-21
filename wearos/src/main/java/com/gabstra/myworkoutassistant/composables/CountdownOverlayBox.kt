package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight.Companion.W700
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text

@Composable
fun CountdownOverlayBox(
    show: Boolean,
    time: Int,
    onVisibilityChange: (Boolean) -> Unit = {},
) {
    val typography = MaterialTheme.typography
    val itemStyle = remember(typography) { typography.numeralLarge.copy(fontWeight = W700) }

    LaunchedEffect(show) {
        onVisibilityChange(show)
    }

    if (show) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(MaterialTheme.colorScheme.background.copy(alpha = 0.85f)),
            contentAlignment = Alignment.Center
        ) {
            Text(
                text = "$time",
                textAlign = TextAlign.Center,
                style = itemStyle
            )
        }
    }
}
