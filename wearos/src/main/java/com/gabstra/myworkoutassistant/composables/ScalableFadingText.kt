package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.PlatformTextStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.LineHeightStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.wear.compose.material3.LocalTextConfiguration
import androidx.wear.compose.material3.LocalTextStyle
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text

@Composable
fun ScalableFadingText(
    text: String,
    modifier: Modifier = Modifier,
    style: TextStyle = LocalTextStyle.current,
    color: Color = MaterialTheme.colorScheme.onBackground,
    fadeWidth: Dp = 12.dp,
    onClick: (() -> Unit)? = null,
    minTextSize: TextUnit = 12.sp,
    scaleDownOnly: Boolean = true,
) {
    ScalableFadingText(
        text = AnnotatedString(text),
        modifier = modifier,
        style = style,
        color = color,
        fadeWidth = fadeWidth,
        onClick = onClick,
        minTextSize = minTextSize,
        scaleDownOnly = scaleDownOnly,
    )
}

@Composable
fun ScalableFadingText(
    text: AnnotatedString,
    modifier: Modifier = Modifier,
    style: TextStyle = LocalTextStyle.current,
    color: Color = MaterialTheme.colorScheme.onBackground,
    fadeWidth: Dp = 12.dp,
    onClick: (() -> Unit)? = null,
    minTextSize: TextUnit = 12.sp,
    scaleDownOnly: Boolean = true,
) {
    val isInspectionMode = LocalInspectionMode.current
    val density = LocalDensity.current
    val fadeColor = MaterialTheme.colorScheme.background

    val measurer = rememberTextMeasurer()

    val baseStyle = remember(style) {
        style.copy(
            platformStyle = PlatformTextStyle(includeFontPadding = false),
            lineHeightStyle = LineHeightStyle(
                alignment = LineHeightStyle.Alignment.Center,
                trim = LineHeightStyle.Trim.Both
            )
        )
    }

    val marqueeState = rememberTrackableMarqueeState()

    BoxWithConstraints(
        modifier = modifier
            .clipToBounds()
            .then(
                if (onClick != null) {
                    Modifier.clickable(onClick = onClick)
                } else {
                    Modifier
                }
            ),
        contentAlignment = Alignment.Center,
    ) {
        val maxWidthPx = with(density) { maxWidth.toPx() }
        val maxHeightPx = with(density) { maxHeight.toPx() }
        val isLayoutReady = maxWidthPx > 1f && maxHeightPx > 1f

        val layout = remember(text, maxWidthPx, maxHeightPx, baseStyle, minTextSize, scaleDownOnly, density) {
            measureScalableSingleLineLayout(
                measurer = measurer,
                text = text,
                maxWidthPx = maxWidthPx,
                maxHeightPx = maxHeightPx,
                baseStyle = baseStyle,
                minTextSize = minTextSize,
                scaleDownOnly = scaleDownOnly,
                density = density,
            )
        }

        val inkWidthPx = with(density) { layout.widthDp.toPx() }
        val hasOverflow = isLayoutReady && inkWidthPx > maxWidthPx

        val textModifier = when {
            isInspectionMode -> Modifier
            hasOverflow ->
                Modifier.trackableMarquee(
                    state = marqueeState,
                    iterations = Int.MAX_VALUE,
                    edgeFadeWidth = fadeWidth,
                    edgeFadeColor = fadeColor,
                )
            else -> Modifier
        }

        val baseModifier = if (isInspectionMode) {
            textModifier
        } else {
            textModifier.graphicsLayer {
                this.alpha = if (isLayoutReady) 1f else 0f
            }
        }

        Box(
            modifier = Modifier
                .then(
                    if (!isInspectionMode && hasOverflow) {
                        Modifier.graphicsLayer(compositingStrategy = CompositingStrategy.Offscreen)
                    } else {
                        Modifier
                    }
                ),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = text,
                style = baseStyle.copy(fontSize = layout.fontSize, color = color),
                color = Color.Unspecified,
                maxLines = 1,
                textAlign = TextAlign.Center,
                overflow = LocalTextConfiguration.current.overflow,
                modifier = baseModifier.then(Modifier.width(layout.widthDp)),
            )
        }
    }
}
