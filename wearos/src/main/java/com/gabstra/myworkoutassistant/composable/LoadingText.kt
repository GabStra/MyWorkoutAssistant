package com.gabstra.myworkoutassistant.composable


import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.Layout
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import kotlinx.coroutines.delay
@Composable
fun LoadingText(baseText: String) {
    val dotCount = remember { mutableIntStateOf(0) }

    LaunchedEffect(Unit) {
        while (true) {
            delay(500)
            dotCount.intValue = (dotCount.intValue + 1) % 4
        }
    }

    // Measure the width of the baseText and the text with 3 dots
    val textWithDots = "$baseText..."
    val textWithDotsWidth = remember { mutableIntStateOf(0) }

    Layout(
        content = {
            Text(
                text = textWithDots,
                style = MaterialTheme.typography.title3,
                color = Color.Transparent,
                onTextLayout = { textLayoutResult ->
                    textWithDotsWidth.intValue = textLayoutResult.size.width
                }
            )
        },
    ) { measurables, constraints ->
        val placeables = measurables.map { it.measure(constraints) }
        layout(0, 0) {
            placeables.forEach { it.place(0, 0) }
        }
    }

    Box(
        modifier = Modifier.width(with(LocalDensity.current) { textWithDotsWidth.intValue.toDp() })
    ) {
        Text(
            text = baseText + ".".repeat(dotCount.intValue),
            style = MaterialTheme.typography.title3,
            color = Color.White
        )
    }
}
