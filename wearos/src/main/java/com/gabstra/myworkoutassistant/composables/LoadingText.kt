package com.gabstra.myworkoutassistant.composables


import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.Layout
import androidx.compose.ui.platform.LocalDensity
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import kotlinx.coroutines.delay

@Composable
fun LoadingText(baseText: String) {
    val dotCount = remember { mutableIntStateOf(0) }

    val textWithDots = "$baseText..."
    val textWithDotsWidth = remember { mutableIntStateOf(0) }

    if(textWithDotsWidth.intValue == 0){
        Layout(
            content = {
                Text(
                    text = textWithDots,
                    style = MaterialTheme.typography.title3,
                    onTextLayout = { textLayoutResult ->
                        textWithDotsWidth.intValue = textLayoutResult.size.width
                    },
                    color = Color.Transparent
                )
            },
        ) { measurables, constraints ->
            val placeables = measurables.map { it.measure(constraints) }
            layout(0, 0) {
                placeables.forEach { it.place(0, 0) }
            }
        }
    }

    LaunchedEffect(textWithDotsWidth.intValue) {
        if (textWithDotsWidth.intValue != 0) {
            while (true) {
                delay(500)
                dotCount.intValue = (dotCount.intValue + 1) % 4
            }
        }
    }

    Box(
        modifier = Modifier.width(with(LocalDensity.current) { textWithDotsWidth.intValue.toDp() })
    ) {
        Text(
            text = baseText + ".".repeat(dotCount.intValue),
            style = MaterialTheme.typography.title3,
        )
    }
}
