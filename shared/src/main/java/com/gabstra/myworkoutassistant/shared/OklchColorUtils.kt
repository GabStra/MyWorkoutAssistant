package com.gabstra.myworkoutassistant.shared

import androidx.compose.ui.graphics.Color
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * OKLCH luminance reduction (perceptual), preserving hue and chroma as much as possible.
 * Pipeline: sRGB -> linear -> OKLab -> OKLCH -> adjust L -> OKLab -> linear -> sRGB (gamut clamp)
 *
 * factor: 0..1 (e.g. 0.8 keeps 80% of OKLCH lightness)
 */
/**
 * Like reduceLuminanceOklch(), but enforces a minimum contrast vs black so it never becomes
 * “invisible”. If the requested factor makes it too dark, it will use the darkest OKLCH L
 * that still meets minContrastOnBlack (without going brighter than the original color).
 *
 * minContrastOnBlack:
 *  - 2.5f  good for non-text UI (icons, strokes)
 *  - 4.5f  for text-level readability
 */
fun reduceLuminanceOklch(
    color: Color,
    factor: Float,
    minContrastOnBlack: Float = 2.5f
): Color {
    val f = factor.coerceIn(0f, 1f)

    val sr = color.red
    val sg = color.green
    val sb = color.blue
    val a  = color.alpha

    val (L, C, h) = srgbToOklch(sr, sg, sb)

    val targetL = (L * f).coerceIn(0f, 1f)

    // Candidate at requested darkness
    run {
        val (r, g, b) = oklchToSrgb(targetL, C, h)
        if (contrastOnBlack(r, g, b, a) >= minContrastOnBlack) {
            return Color(r, g, b, a)
        }
    }

    // If even the original doesn’t meet the threshold, don’t try to “fix” by brightening past it
    run {
        val origContrast = contrastOnBlack(sr, sg, sb, a)
        if (origContrast < minContrastOnBlack) return color
    }

    // Binary search L in [targetL, L] to find the darkest that still passes
    var lo = targetL
    var hi = L
    var bestL = L

    repeat(24) {
        val mid = (lo + hi) * 0.5f
        val (r, g, b) = oklchToSrgb(mid, C, h)
        val cr = contrastOnBlack(r, g, b, a)

        if (cr >= minContrastOnBlack) {
            bestL = mid
            hi = mid // try darker
        } else {
            lo = mid // need brighter
        }
    }

    val (nr, ng, nb) = oklchToSrgb(bestL, C, h)
    return Color(nr, ng, nb, a)
}

/* ---------- Contrast vs black (alpha-aware) ---------- */

private fun contrastOnBlack(r: Float, g: Float, b: Float, a: Float): Float {
    // Blend over black in *linear* space (black = 0), then compute WCAG luminance.
    val rl = srgbToLinear(r) * a
    val gl = srgbToLinear(g) * a
    val bl = srgbToLinear(b) * a
    val y = 0.2126f * rl + 0.7152f * gl + 0.0722f * bl
    return (y + 0.05f) / 0.05f
}

/**
 * OKLCH chroma reduction (recommended for "long sessions" on black).
 * Keeps lightness fixed and hue fixed; reduces chroma (colorfulness) perceptually.
 */
fun reduceChromaOklch(color: Color, factor: Float): Color {
    val f = factor.coerceIn(0f, 1f)

    val sr = color.red
    val sg = color.green
    val sb = color.blue
    val a = color.alpha

    val (L, C, h) = srgbToOklch(sr, sg, sb)

    val newC = (C * f).coerceAtLeast(0f)
    val (nr, ng, nb) = oklchToSrgb(L, newC, h)

    return Color(nr, ng, nb, a)
}

/* ----------------------------- OKLCH conversions ----------------------------- */

private fun srgbToOklch(r: Float, g: Float, b: Float): Oklch {
    // sRGB -> linear
    val rl = srgbToLinear(r)
    val gl = srgbToLinear(g)
    val bl = srgbToLinear(b)

    // linear sRGB -> LMS (OKLab)
    val l = 0.4122214708f * rl + 0.5363325363f * gl + 0.0514459929f * bl
    val m = 0.2119034982f * rl + 0.6806995451f * gl + 0.1073969566f * bl
    val s = 0.0883024619f * rl + 0.2817188376f * gl + 0.6299787005f * bl

    // cube-root
    val l_ = cbrtSafe(l)
    val m_ = cbrtSafe(m)
    val s_ = cbrtSafe(s)

    // LMS -> OKLab
    val L = 0.2104542553f * l_ + 0.7936177850f * m_ - 0.0040720468f * s_
    val a = 1.9779984951f * l_ - 2.4285922050f * m_ + 0.4505937099f * s_
    val b2 = 0.0259040371f * l_ + 0.7827717662f * m_ - 0.8086757660f * s_

    val C = hypot(a, b2)
    val hRad = atan2(b2.toDouble(), a.toDouble())
    val hDeg = ((hRad * 180.0 / Math.PI) % 360.0 + 360.0) % 360.0

    return Oklch(
        L = L.coerceIn(0f, 1f),
        C = C,
        hDeg = hDeg.toFloat()
    )
}

private fun oklchToSrgb(L: Float, C: Float, hDeg: Float): Triple<Float, Float, Float> {
    val hRad = (hDeg.toDouble() * Math.PI / 180.0)
    val a = (C * cos(hRad)).toFloat()
    val b = (C * sin(hRad)).toFloat()

    // OKLab -> LMS'
    val l_ = L + 0.3963377774f * a + 0.2158037573f * b
    val m_ = L - 0.1055613458f * a - 0.0638541728f * b
    val s_ = L - 0.0894841775f * a - 1.2914855480f * b

    // cube
    val l = l_ * l_ * l_
    val m = m_ * m_ * m_
    val s = s_ * s_ * s_

    // LMS -> linear sRGB
    val rl = +4.0767416621f * l - 3.3077115913f * m + 0.2309699292f * s
    val gl = -1.2684380046f * l + 2.6097574011f * m - 0.3413193965f * s
    val bl = -0.0041960863f * l - 0.7034186147f * m + 1.7076147010f * s

    // linear -> sRGB with clamp
    val r = linearToSrgb(rl).coerceIn(0f, 1f)
    val g = linearToSrgb(gl).coerceIn(0f, 1f)
    val bOut = linearToSrgb(bl).coerceIn(0f, 1f)

    return Triple(r, g, bOut)
}

/* ----------------------------- helpers ----------------------------- */

private fun srgbToLinear(x: Float): Float {
    val v = x.coerceIn(0f, 1f)
    return if (v <= 0.04045f) v / 12.92f else ((v + 0.055f) / 1.055f).pow(2.4f)
}

private fun linearToSrgb(x: Float): Float {
    val v = x
    return if (v <= 0.0031308f) 12.92f * v else 1.055f * v.pow(1f / 2.4f) - 0.055f
}

private fun cbrtSafe(x: Float): Float {
    // x should be >= 0 here, but guard anyway
    return if (x >= 0f) x.toDouble().pow(1.0 / 3.0).toFloat()
    else -((-x).toDouble().pow(1.0 / 3.0)).toFloat()
}

private fun hypot(a: Float, b: Float): Float =
    sqrt(a * a + b * b)
