package com.gabstra.myworkoutassistant.composables

import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.drawOutline
import androidx.compose.ui.unit.LayoutDirection
import kotlin.math.pow

fun Modifier.subtleVerticalGradientBackground(
    base: Color,
    shape: Shape,
    deltaLightness: Float = 0.08f,   // Wear OS: 0.06–0.12
    highlightAlpha: Float = 0.03f,   // 0.02–0.06
    gradientSpan: Float = 0.55f,     // portion of height used for gradient (0.35–0.7)
): Modifier = this.then(
    Modifier.drawWithCache {
        val d = deltaLightness.coerceIn(0f, 0.18f)
        val outline = shape.createOutline(size, LayoutDirection.Ltr, this)

        // Make the change happen sooner (top part) so it’s visible on short buttons
        val endY = (size.height * gradientSpan.coerceIn(0.1f, 1f)).coerceAtLeast(1f)

        val top = base.adjustOklabLightness(+d)
        val bottom = base

        val brush = Brush.verticalGradient(
            colors = listOf(top, bottom),
            startY = 0f,
            endY = endY
        )

        // tiny top specular highlight
        val highlight = Brush.verticalGradient(
            colors = listOf(Color.White.copy(alpha = highlightAlpha.coerceIn(0f, 0.12f)), Color.Transparent),
            startY = 0f,
            endY = (size.height * 0.25f).coerceAtLeast(1f)
        )

        onDrawBehind {
            drawOutline(outline, brush)
            drawOutline(outline, highlight)
        }
    }
)

/**
 * OKLab lightness adjust:
 * - Convert sRGB -> linear -> OKLab
 * - Add delta to L
 * - Convert back to sRGB
 */
private fun Color.adjustOklabLightness(deltaL: Float): Color {
    val a0 = alpha

    fun srgbToLinear(c: Float): Float =
        if (c <= 0.04045f) c / 12.92f else ((c + 0.055f) / 1.055f).pow(2.4f)

    fun linearToSrgb(c: Float): Float =
        if (c <= 0.0031308f) 12.92f * c else 1.055f * c.pow(1f / 2.4f) - 0.055f

    val r = srgbToLinear(red)
    val g = srgbToLinear(green)
    val b = srgbToLinear(blue)

    // linear sRGB -> LMS
    val l = 0.4122214708f * r + 0.5363325363f * g + 0.0514459929f * b
    val m = 0.2119034982f * r + 0.6806995451f * g + 0.1073969566f * b
    val s = 0.0883024619f * r + 0.2817188376f * g + 0.6299787005f * b

    fun cbrt(x: Float) = x.pow(1f / 3f)

    val l_ = cbrt(l)
    val m_ = cbrt(m)
    val s_ = cbrt(s)

    // LMS -> OKLab
    var L = 0.2104542553f * l_ + 0.7936177850f * m_ - 0.0040720468f * s_
    val A = 1.9779984951f * l_ - 2.4285922050f * m_ + 0.4505937099f * s_
    val B = 0.0259040371f * l_ + 0.7827717662f * m_ - 0.8086757660f * s_

    L = (L + deltaL).coerceIn(0f, 1f)

    // OKLab -> LMS
    val l2 = (L + 0.3963377774f * A + 0.2158037573f * B).pow(3f)
    val m2 = (L - 0.1055613458f * A - 0.0638541728f * B).pow(3f)
    val s2 = (L - 0.0894841775f * A - 1.2914855480f * B).pow(3f)

    // LMS -> linear sRGB
    val r2 = +4.0767416621f * l2 - 3.3077115913f * m2 + 0.2309699292f * s2
    val g2 = -1.2684380046f * l2 + 2.6097574011f * m2 - 0.3413193965f * s2
    val b2 = -0.0041960863f * l2 - 0.7034186147f * m2 + 1.7076147010f * s2

    // linear -> sRGB and clamp
    val rr = linearToSrgb(r2).coerceIn(0f, 1f)
    val gg = linearToSrgb(g2).coerceIn(0f, 1f)
    val bb = linearToSrgb(b2).coerceIn(0f, 1f)

    return Color(rr, gg, bb, a0)
}
