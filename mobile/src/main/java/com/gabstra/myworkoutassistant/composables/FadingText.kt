package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun FadingText(
    text: String,
    modifier: Modifier = Modifier,
    style: TextStyle = MaterialTheme.typography.bodyMedium,
    color: Color = MaterialTheme.colorScheme.onBackground,
    fadeWidth: Dp = 16.dp,
    marqueeEnabled: Boolean = false,
    onClick: (() -> Unit)? = null,
) {
    FadingText(
        text = AnnotatedString(text),
        modifier = modifier,
        style = style,
        color = color,
        fadeWidth = fadeWidth,
        marqueeEnabled = marqueeEnabled,
        onClick = onClick
    )
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun FadingText(
    text: AnnotatedString,
    modifier: Modifier = Modifier,
    style: TextStyle = MaterialTheme.typography.bodyMedium,
    color: Color = MaterialTheme.colorScheme.onBackground,
    fadeWidth: Dp = 16.dp,
    marqueeEnabled: Boolean = false,
    onClick: (() -> Unit)? = null,
) {
    val density = LocalDensity.current
    val fadeWidthPx = with(density) { fadeWidth.toPx() }
    val fadeColor = MaterialTheme.colorScheme.surface
    
    var textLayoutResult: TextLayoutResult? by remember { mutableStateOf(null) }
    var containerWidth: Float by remember { mutableStateOf(0f) }
    
    val hasOverflow = remember(textLayoutResult, containerWidth) {
        textLayoutResult?.let { layoutResult ->
            layoutResult.size.width > containerWidth
        } ?: false
    }
    
    val textModifier = modifier
        .fillMaxWidth()
        .onGloballyPositioned { coordinates ->
            containerWidth = coordinates.size.width.toFloat()
        }
        .then(
            if (marqueeEnabled) {
                Modifier.basicMarquee(iterations = Int.MAX_VALUE)
            } else {
                Modifier
            }
        )
        .then(
            if (onClick != null) {
                Modifier.clickable(onClick = onClick)
            } else {
                Modifier
            }
        )
        .drawWithContent {
            drawContent()
            
            if (hasOverflow && containerWidth > 0f) {
                // Left fade
                val leftFadeBrush = Brush.horizontalGradient(
                    colors = listOf(fadeColor, Color.Transparent),
                    startX = 0f,
                    endX = fadeWidthPx.coerceAtMost(containerWidth / 2f)
                )
                drawRect(
                    brush = leftFadeBrush,
                    topLeft = Offset.Zero,
                    size = Size(fadeWidthPx.coerceAtMost(containerWidth / 2f), size.height)
                )
                
                // Right fade
                val rightFadeStart = containerWidth - fadeWidthPx.coerceAtMost(containerWidth / 2f)
                val rightFadeBrush = Brush.horizontalGradient(
                    colors = listOf(Color.Transparent, fadeColor),
                    startX = rightFadeStart,
                    endX = containerWidth
                )
                drawRect(
                    brush = rightFadeBrush,
                    topLeft = Offset(rightFadeStart, 0f),
                    size = Size(fadeWidthPx.coerceAtMost(containerWidth / 2f), size.height)
                )
            }
        }
    
    Text(
        text = text,
        style = style,
        color = color,
        modifier = textModifier,
        onTextLayout = { layoutResult ->
            textLayoutResult = layoutResult
        },
        maxLines = 1
    )
}
