package com.gabstra.myworkoutassistant.workout


import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.rememberTextMeasurer
import kotlinx.coroutines.delay

@Composable
fun LoadingText(
    baseText: String,
    style: TextStyle = MaterialTheme.typography.titleMedium
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

    val dotCount = remember { mutableIntStateOf(0) }

    LaunchedEffect(Unit) {
        while (true) {
            delay(500)
            dotCount.intValue = (dotCount.intValue + 1) % 4
        }
    }

    Box(Modifier.width(fullWidthDp)) {
        Text(
            text = baseText + ".".repeat(dotCount.intValue),
            style = style,
            maxLines = 1
        )
    }
}

