package com.gabstra.myworkoutassistant.composables

import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Outline
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.drawOutline
import androidx.compose.ui.unit.LayoutDirection
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

/**
 * Replaces a flat background with a subtle vertical lightness gradient:
 * top is slightly lighter, bottom is the base color.
 *
 * deltaLightness: 0.02–0.04 is usually enough on black backgrounds.
 */
fun Modifier.subtleVerticalGradientBackground(
    base: Color,
    shape: Shape,
    deltaLightness: Float = 0.03f,
): Modifier = this.then(
    Modifier.drawWithCache {
        val d = deltaLightness.coerceIn(0f, 0.12f)
        val top = base.adjustHslLightness(+d)
        val bottom = base

        val outline: Outline = shape.createOutline(size, LayoutDirection.Ltr, this)

        val brush = Brush.verticalGradient(
            colors = listOf(top, bottom),
            startY = 0f,
            endY = size.height
        )

        onDrawBehind {
            drawOutline(outline = outline, brush = brush)
        }
    }
)

/** Minimal RGB <-> HSL lightness adjust (keeps hue/sat roughly stable). */
private fun Color.adjustHslLightness(delta: Float): Color {
    val a = alpha
    val r = red
    val g = green
    val b = blue

    val maxC = max(r, max(g, b))
    val minC = min(r, min(g, b))
    val c = maxC - minC

    val l = (maxC + minC) / 2f

    val s = if (c == 0f) 0f else c / (1f - abs(2f * l - 1f))

    val h = when {
        c == 0f -> 0f
        maxC == r -> ((g - b) / c).mod(6f)
        maxC == g -> ((b - r) / c) + 2f
        else -> ((r - g) / c) + 4f
    } * 60f

    val newL = (l + delta).coerceIn(0f, 1f)
    return hslToColor(h, s, newL, a)
}

private fun hslToColor(hDeg: Float, s: Float, l: Float, a: Float): Color {
    val c = (1f - abs(2f * l - 1f)) * s
    val h = ((hDeg % 360f) + 360f) % 360f
    val x = c * (1f - abs((h / 60f) % 2f - 1f))
    val (rp, gp, bp) = when {
        h < 60f -> Triple(c, x, 0f)
        h < 120f -> Triple(x, c, 0f)
        h < 180f -> Triple(0f, c, x)
        h < 240f -> Triple(0f, x, c)
        h < 300f -> Triple(x, 0f, c)
        else -> Triple(c, 0f, x)
    }
    val m = l - c / 2f
    return Color(rp + m, gp + m, bp + m, a)
}
