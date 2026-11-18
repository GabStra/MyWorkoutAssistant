package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.wrapContentHeight

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.LocalTextStyle
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text

@Composable
fun FadingText(
    text: String,
    modifier: Modifier = Modifier,
    style: TextStyle = LocalTextStyle.current,
    color: Color = MaterialTheme.colorScheme.onBackground,
    fadeWidth: Dp = 12.dp,
    textAlign: TextAlign? = null,
    onClick: (() -> Unit)? = null,
) {
    FadingText(
        text = AnnotatedString(text),
        modifier = modifier,
        style = style,
        color = color,
        fadeWidth = fadeWidth,
        textAlign = textAlign,
        onClick = onClick
    )
}

@Composable
fun FadingText(
    text: AnnotatedString,
    modifier: Modifier = Modifier,
    style: TextStyle = LocalTextStyle.current,
    color: Color = MaterialTheme.colorScheme.onBackground,
    fadeWidth: Dp = 12.dp,
    textAlign: TextAlign? = null,
    onClick: (() -> Unit)? = null,
) {
    val isInspectionMode = false //LocalInspectionMode.current
    val density = LocalDensity.current
    val fadeColor = MaterialTheme.colorScheme.background

    var textLayoutResult: TextLayoutResult? by remember { mutableStateOf(null) }
    var containerWidth by remember { mutableFloatStateOf(0f) }

    val hasOverflow = remember(textLayoutResult, containerWidth) {
        if (containerWidth <= 0f) false
        else textLayoutResult?.let { it.hasVisualOverflow || it.size.width.toFloat() > containerWidth } ?: false
    }

    val marqueeState = rememberTrackableMarqueeState()

    // Numeric styles that fit get the same ink-tight box as TightNumericText; the marquee
    // keeps its clipping box because it animates inside a fixed viewport.
    val tightNumeric = !isInspectionMode && !hasOverflow && style.isTightNumericStyle()
    val tightHeight = if (tightNumeric) {
        with(density) { (style.fontSize * NumericLineHeightScale).toDp() }
    } else {
        0.dp
    }

    // Wrap content by default so Weight(1f, fill = false) parents can shrink to their text;
    // callers that need full width pass Modifier.fillMaxWidth() themselves.
    val boxModifier = modifier
        .then(if (tightNumeric) Modifier.height(tightHeight) else Modifier.clipToBounds())
        .then(
            // Offscreen compositing is only needed while the marquee is scrolling (fading edges).
            if (!isInspectionMode && hasOverflow) {
                Modifier.graphicsLayer(compositingStrategy = CompositingStrategy.Offscreen)
            } else {
                Modifier
            }
        )
        .onGloballyPositioned { containerWidth = it.size.width.toFloat() }
        .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)

    val textModifier = if (!isInspectionMode && hasOverflow) {
        Modifier
            .fillMaxWidth()
            .trackableMarquee(
                state = marqueeState,
                iterations = Int.MAX_VALUE,
                // fades are drawn inside the marquee node (updates every frame)
                edgeFadeWidth = fadeWidth,
                edgeFadeColor = fadeColor,
            )
    } else if (tightNumeric) {
        // Unbounded measurement so the clamped box trims layout space without clipping glyphs.
        Modifier.wrapContentHeight(unbounded = true)
    } else {
        // Fitting text wraps to its content; the marquee branch above still fills the
        // available width so the scroll viewport is stable.
        Modifier
    }

    // Fitting text wraps to its content, so textAlign cannot place it: the Box alignment must.
    val contentAlignment = when (textAlign) {
        TextAlign.Start, TextAlign.Left -> Alignment.CenterStart
        TextAlign.End, TextAlign.Right -> Alignment.CenterEnd
        else -> Alignment.Center
    }

    Box(modifier = boxModifier, contentAlignment = contentAlignment) {
        Text(
            text = text,
            style = style,
            color = color,
            modifier = textModifier,
            textAlign = textAlign,
            onTextLayout = { textLayoutResult = it },
            maxLines = 1,
            overflow = TextOverflow.Clip,
            softWrap = false
        )
    }
}
