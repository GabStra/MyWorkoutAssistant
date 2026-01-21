package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.wrapContentWidth
import androidx.compose.ui.Alignment
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.PlatformTextStyle
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.LineHeightStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.unit.TextUnit
import androidx.wear.compose.material3.LocalTextStyle
import androidx.wear.compose.material3.MaterialTheme
import kotlin.math.min

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun ScalableFadingText(
    text: String,
    modifier: Modifier = Modifier,
    style: TextStyle = LocalTextStyle.current,
    color: Color = MaterialTheme.colorScheme.onBackground,
    fadeWidth: Dp = 12.dp,
    marqueeEnabled: Boolean = false,
    textAlign: TextAlign? = null,
    onClick: (() -> Unit)? = null,
    minTextSize: TextUnit = 12.sp,
    scaleDownOnly: Boolean = true,
    fadeInMillis: Int = 600,
) {
    ScalableFadingText(
        text = AnnotatedString(text),
        modifier = modifier,
        style = style,
        color = color,
        fadeWidth = fadeWidth,
        marqueeEnabled = marqueeEnabled,
        textAlign = textAlign,
        onClick = onClick,
        minTextSize = minTextSize,
        scaleDownOnly = scaleDownOnly,
        fadeInMillis = fadeInMillis
    )
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun ScalableFadingText(
    text: AnnotatedString,
    modifier: Modifier = Modifier,
    style: TextStyle = LocalTextStyle.current,
    color: Color = MaterialTheme.colorScheme.onBackground,
    fadeWidth: Dp = 12.dp,
    marqueeEnabled: Boolean = false,
    textAlign: TextAlign? = null,
    onClick: (() -> Unit)? = null,
    minTextSize: TextUnit = 12.sp,
    scaleDownOnly: Boolean = true,
    fadeInMillis: Int = 600,
) {
    val density = LocalDensity.current
    val fadeWidthPx = with(density) { fadeWidth.toPx() }
    val fadeColor = MaterialTheme.colorScheme.background
    
    // Convert AnnotatedString to String for ScalableText
    val textString = text.text
    
    // Use text measurer to detect overflow
    val measurer = rememberTextMeasurer()
    var containerWidth: Float by remember { mutableStateOf(0f) }
    var containerHeight: Float by remember { mutableStateOf(0f) }
    
    // Configure base style once (same as ScalableText)
    val baseStyle = remember(style) {
        style.copy(
            platformStyle = PlatformTextStyle(includeFontPadding = false),
            lineHeightStyle = LineHeightStyle(
                alignment = LineHeightStyle.Alignment.Center,
                trim = LineHeightStyle.Trim.Both
            )
        )
    }
    
    // Calculate fitted size using ScalableText logic
    val fittedSize = remember(textString, containerWidth, containerHeight, baseStyle, minTextSize, scaleDownOnly) {
        if (containerWidth <= 0f || containerHeight <= 0f) return@remember minTextSize
        
        val baseFontSize = baseStyle.fontSize
        val upperBound = if (scaleDownOnly) baseFontSize
        else if (baseFontSize.value >= 32f) baseFontSize else 32.sp
        
        // Measure text at the largest allowed size
        val result = measurer.measure(
            text = textString,
            style = baseStyle.copy(fontSize = upperBound),
            maxLines = 1,
            softWrap = false
        )
        
        // Calculate ratios for both dimensions
        val widthRatio = if (result.size.width > 0) containerWidth / result.size.width else 1f
        val heightRatio = if (result.size.height > 0) containerHeight / result.size.height else 1f
        
        // Pick the strictest constraint (smallest ratio)
        val bestRatio = min(widthRatio, heightRatio)
        
        // Apply ratio
        val finalSize = if (bestRatio < 1f || !scaleDownOnly) {
            (upperBound.value * bestRatio)
        } else {
            upperBound.value
        }
        
        finalSize.coerceAtLeast(minTextSize.value).sp
    }
    
    // Measure text at fitted size to detect actual overflow after scaling
    val scaledTextLayoutResult = remember(textString, fittedSize, containerWidth, baseStyle) {
        if (containerWidth > 0f) {
            measurer.measure(
                text = textString,
                style = baseStyle.copy(fontSize = fittedSize),
                maxLines = 1,
                softWrap = false
            )
        } else {
            null
        }
    }
    
    val hasOverflow = remember(scaledTextLayoutResult, containerWidth) {
        if (containerWidth <= 0f) {
            false
        } else {
            scaledTextLayoutResult?.size?.width?.toFloat()?.let { it > containerWidth } ?: false
        }
    }
    
    val marqueeActive = marqueeEnabled || hasOverflow
    
    val boxModifier = modifier
        .fillMaxWidth()
        .clipToBounds()
        .graphicsLayer(compositingStrategy = CompositingStrategy.Offscreen)
        .onGloballyPositioned { coordinates ->
            containerWidth = coordinates.size.width.toFloat()
        }
        .then(
            if (onClick != null) {
                Modifier.clickable(onClick = onClick)
            } else {
                Modifier
            }
        )
        .drawWithContent {
            drawContent()
            
            if (containerWidth > 0f && marqueeActive) {
                val fadeSize = fadeWidthPx.coerceAtMost(containerWidth / 2f)
                
                val leftFadeBrush = Brush.horizontalGradient(
                    colors = listOf(fadeColor, fadeColor.copy(alpha = 0f)),
                    startX = 0f,
                    endX = fadeSize
                )
                drawRect(
                    brush = leftFadeBrush,
                    topLeft = Offset.Zero,
                    size = Size(fadeSize, size.height)
                )
                
                val rightFadeStart = containerWidth - fadeSize
                val rightFadeBrush = Brush.horizontalGradient(
                    colors = listOf(fadeColor.copy(alpha = 0f), fadeColor),
                    startX = rightFadeStart,
                    endX = containerWidth
                )
                drawRect(
                    brush = rightFadeBrush,
                    topLeft = Offset(rightFadeStart, 0f),
                    size = Size(fadeSize, size.height)
                )
            }
        }
    
    val textModifier = if (marqueeActive) {
        Modifier.basicMarquee(iterations = Int.MAX_VALUE)
    } else {
        Modifier.wrapContentWidth(unbounded = true)
    }

    Box(modifier = boxModifier, contentAlignment = Alignment.Center) {
        ScalableText(
            text = textString,
            modifier = Modifier.fillMaxWidth(),
            textModifier = textModifier,
            color = color,
            style = style,
            textAlign = textAlign,
            minTextSize = minTextSize,
            scaleDownOnly = scaleDownOnly,
            fadeInMillis = fadeInMillis
        )
    }
}
