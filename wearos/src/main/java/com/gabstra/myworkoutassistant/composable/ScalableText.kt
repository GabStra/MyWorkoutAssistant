package com.gabstra.myworkoutassistant.composable

import android.util.Log
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material3.LocalTextStyle
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.wear.compose.material.Text

@Composable
fun ScalableText(
    modifier: Modifier = Modifier,
    text: String,
    color: Color = Color.Unspecified,
    style: TextStyle = LocalTextStyle.current // Provide a default TextStyle
) {
    var textSize by remember { mutableStateOf(100.sp) } // Start with a large font size
    var readyToScale by remember { mutableStateOf(false) } // Trigger recalculation
    var initialRender by remember { mutableStateOf(true) } // Track the first render
    val density = LocalDensity.current
    val textMeasurer = rememberTextMeasurer() // Initialize the text measurer

    val shouldBeInvisible = initialRender || readyToScale

    BoxWithConstraints(
        modifier = modifier
    ) {
        val boxWidth = maxWidth
        val boxHeight = maxHeight

        // Measure the text with the current font size
        val textLayoutResult = textMeasurer.measure(
            text = text,
            style = style.copy(fontSize = textSize)
        )

        Text(
            text = text,
            style = style.copy(fontSize = textSize),
            maxLines = 1,
            color = color,
            modifier = Modifier
                .alpha(if (shouldBeInvisible) 0f else 1f)
                .onGloballyPositioned { coordinates ->
                    initialRender = false // Update the initial render flag

                    val textWidth = with(density) { textLayoutResult.size.width.toDp() }
                    val textHeight = with(density) { textLayoutResult.size.height.toDp() }

                    // If the text exceeds the container's size, trigger scaling
                    readyToScale = textWidth > boxWidth || textHeight > boxHeight
                }
        )

        // Use LaunchedEffect to handle scaling in a loop
        LaunchedEffect(readyToScale) {
            while (readyToScale) {
                textSize *= 0.9f // Keep reducing the text size until it fits
                // Re-measure the text with the new font size
                val newTextLayoutResult = textMeasurer.measure(
                    text = text,
                    style = style.copy(fontSize = textSize)
                )
                val newTextWidth = with(density) { newTextLayoutResult.size.width.toDp() }
                val newTextHeight = with(density) { newTextLayoutResult.size.height.toDp() }

                if (newTextWidth <= boxWidth && newTextHeight <= boxHeight) {
                    readyToScale = false // Stop scaling once it fits
                }
            }
        }
    }
}