package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.PlatformTextStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.LineHeightStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.sp
import androidx.wear.compose.material3.LocalTextConfiguration
import androidx.wear.compose.material3.LocalTextStyle
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import kotlin.math.min

@Composable
fun ScalableText(
    text: String,
    modifier: Modifier = Modifier,
    textModifier: Modifier = Modifier,
    color: Color = MaterialTheme.colorScheme.onBackground,
    style: TextStyle = LocalTextStyle.current,
    textAlign: TextAlign? = TextAlign.Center,
    overflow: TextOverflow = LocalTextConfiguration.current.overflow,
    minTextSize: TextUnit = 12.sp,
    contentAlignment: Alignment = Alignment.Center,
    scaleDownOnly: Boolean = true
) {
    ScalableText(
        text = AnnotatedString(text),
        modifier = modifier,
        textModifier = textModifier,
        color = color,
        style = style,
        textAlign = textAlign,
        overflow = overflow,
        minTextSize = minTextSize,
        contentAlignment = contentAlignment,
        scaleDownOnly = scaleDownOnly
    )
}

@Composable
fun ScalableText(
    text: AnnotatedString,
    modifier: Modifier = Modifier,
    textModifier: Modifier = Modifier,
    color: Color = MaterialTheme.colorScheme.onBackground,
    style: TextStyle = LocalTextStyle.current,
    textAlign: TextAlign? = TextAlign.Center,
    overflow: TextOverflow = LocalTextConfiguration.current.overflow,
    minTextSize: TextUnit = 12.sp,
    contentAlignment: Alignment = Alignment.Center,
    scaleDownOnly: Boolean = true
) {
    val isInspectionMode = LocalInspectionMode.current

    val measurer = rememberTextMeasurer()
    val density = LocalDensity.current

    // Optimize: Configure base style once to avoid repeated allocations
    val baseStyle = remember(style) {
        style.copy(
            platformStyle = PlatformTextStyle(includeFontPadding = false),
            lineHeightStyle = LineHeightStyle(
                alignment = LineHeightStyle.Alignment.Center,
                trim = LineHeightStyle.Trim.Both
            )
        )
    }

    BoxWithConstraints(modifier = modifier, contentAlignment = contentAlignment) {
        val maxWidthPx = with(density) { maxWidth.toPx() }
        val maxHeightPx = with(density) { maxHeight.toPx() }

        // Safety check to ensure layout is actually ready before we calculate
        val isLayoutReady = maxWidthPx > 1 && maxHeightPx > 1

        // 1. Calculate the ideal font size (Linear Math - Fast O(1))
        val fittedSize = remember(text, maxWidthPx, maxHeightPx, baseStyle, minTextSize, scaleDownOnly) {
            if (!isLayoutReady) return@remember minTextSize

            val baseFontSize = baseStyle.fontSize
            val upperBound = if (scaleDownOnly) baseFontSize
            else if (baseFontSize.value >= 32f) baseFontSize else 32.sp

            // Measure text ONCE at the largest allowed size
            val result = measurer.measure(
                text = text,
                style = baseStyle.copy(fontSize = upperBound),
                maxLines = 1,
                softWrap = false
            )

            // Calculate ratios for both dimensions
            val widthRatio = if (result.size.width > 0) maxWidthPx / result.size.width else 1f
            val heightRatio = if (result.size.height > 0) maxHeightPx / result.size.height else 1f

            // Pick the strictest constraint (smallest ratio)
            val bestRatio = min(widthRatio, heightRatio)

            // Apply ratio
            val finalSize = if (bestRatio < 1f || !scaleDownOnly) {
                (upperBound.value * bestRatio)
            } else {
                upperBound.value
            }

            // Return SP directly for instant application
            finalSize.coerceAtLeast(minTextSize.value).sp
        }

        val fittedTextWidth = remember(text, fittedSize, baseStyle) {
            val result = measurer.measure(
                text = text,
                style = baseStyle.copy(fontSize = fittedSize),
                maxLines = 1,
                softWrap = false
            )
            with(density) { result.size.width.toDp() }
        }

        val baseModifier = if (isInspectionMode) {
            textModifier
        } else {
            textModifier.graphicsLayer {
                this.alpha = if (isLayoutReady) 1f else 0f
            }
        }

        Text(
            text = text,
            style = baseStyle.copy(fontSize = fittedSize),
            color = color,
            maxLines = 1,
            textAlign = textAlign,
            overflow = overflow,
            modifier = baseModifier.then(Modifier.width(fittedTextWidth))
        )
    }
}
