package com.gabstra.myworkoutassistant.composables


import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import kotlinx.coroutines.delay

@Composable
fun LoadingText(
    baseText: String,
    style: TextStyle = MaterialTheme.typography.titleMedium,
    color: Color = Color.Unspecified,
) {
    val measurer = rememberTextMeasurer()
    val density = LocalDensity.current

    // Measure once for "baseText..."
    val fullWidthDp = remember(measurer, baseText, style, density) {
        with(density) {
            measurer
                .measure(text = AnnotatedString("$baseText..."), style = style, maxLines = 1)
                .size.width
                .toDp()
        }
    }

    val dotCount = remember { mutableIntStateOf(1) }

    LaunchedEffect(Unit) {
        while (true) {
            delay(500)
            dotCount.intValue = (dotCount.intValue % 3) + 1  // cycles 1→2→3→1
        }
    }

    Box(Modifier.width(fullWidthDp)) {
        Text(
            text = baseText + ".".repeat(dotCount.intValue),
            style = style,
            color = color,
            maxLines = 1
        )
    }
}
