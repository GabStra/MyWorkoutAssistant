package com.gabstra.myworkoutassistant.composables

import android.R.attr.maxLines
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.PlatformTextStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.LineHeightStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.sp
import androidx.wear.compose.material3.LocalTextConfiguration
import androidx.wear.compose.material3.LocalTextStyle
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import kotlin.math.abs

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
    fadeInMillis: Int = 250,
    scaleDownOnly: Boolean = true
) {
    val measurer = rememberTextMeasurer()
    val density = LocalDensity.current

    BoxWithConstraints(modifier = modifier, contentAlignment = contentAlignment) {
        val maxWidthPx = with(density) { maxWidth.toPx().toInt() }
        val maxHeightPx = with(density) { maxHeight.toPx().toInt() }

        val baseSize = style.fontSize
        val upperBound = if (scaleDownOnly) baseSize
        else if (baseSize.value >= 32f) baseSize else 32.sp

        val fittedSize = remember(text, maxWidthPx, maxHeightPx, minTextSize, upperBound, style, maxLines) {
            fun fits(size: TextUnit): Boolean {
                val r = measurer.measure(
                    text = text,
                    style = style.copy(
                        fontSize = size,
                        platformStyle = PlatformTextStyle(includeFontPadding = false),
                        lineHeightStyle = LineHeightStyle(
                            alignment = LineHeightStyle.Alignment.Center,
                            trim = LineHeightStyle.Trim.Both
                        )
                    ),
                    maxLines = 1,
                    softWrap = false,
                    overflow = TextOverflow.Clip,
                    constraints = Constraints(maxWidth = maxWidthPx , maxHeight = maxHeightPx)
                )

                return r.size.width <= maxWidthPx + 1 &&
                        r.size.height <= maxHeightPx + 1 &&
                        !r.hasVisualOverflow
            }

            if (!fits(minTextSize)) return@remember minTextSize
            if (fits(upperBound)) return@remember upperBound

            var lo = minTextSize.value
            var hi = upperBound.value
            var best = lo
            var i = 0
            while (i < 16 && abs(hi - lo) > 0.5f) {
                val mid = (lo + hi) / 2f
                if (fits(mid.sp)) {
                    best = mid
                    lo = mid
                } else {
                    hi = mid
                }
                i++
            }

            best.sp
        }

        var show by remember { mutableStateOf(false) }
        LaunchedEffect(Unit) { show = true }
        val alpha by animateFloatAsState(
            if (show) 1f else 0f, tween(fadeInMillis), label = "ScalableTextFade"
        )

        Text(
            text = text,
            style = style.copy(
                fontSize = fittedSize,
                platformStyle = PlatformTextStyle(includeFontPadding = false),
                lineHeightStyle = LineHeightStyle(
                    alignment = LineHeightStyle.Alignment.Center,
                    trim = LineHeightStyle.Trim.Both
                )
            ),
            color = color,
            maxLines = 1,
            textAlign = textAlign,
            overflow = overflow,
            modifier = if(fadeInMillis > 200) Modifier.alpha(alpha).then(textModifier) else Modifier.alpha(if (show) 1f else 0f).then(textModifier)
        )
    }
}