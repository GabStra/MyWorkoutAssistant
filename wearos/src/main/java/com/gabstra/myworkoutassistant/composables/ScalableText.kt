package com.gabstra.myworkoutassistant.composables

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Rect
import android.graphics.Typeface
import android.os.Build
import android.text.TextPaint
import android.text.TextUtils
import android.util.TypedValue
import android.view.Gravity
import android.view.ViewGroup
import androidx.appcompat.widget.AppCompatTextView
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.LinearOutSlowInEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.layout.SubcomposeLayout
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalFontFamilyResolver
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.PlatformTextStyle
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontSynthesis
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.LineHeightStyle
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.TextUnitType
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.wear.compose.material3.LocalTextConfiguration
import androidx.wear.compose.material3.LocalTextStyle
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import kotlinx.coroutines.delay
import kotlin.math.ceil
import kotlin.math.min

@Composable
fun ScalableText(
    text: String,
    modifier: Modifier = Modifier,
    textModifier: Modifier = Modifier,
    color: Color = MaterialTheme.colorScheme.onBackground,
    style: TextStyle = LocalTextStyle.current,
    overflow: TextOverflow = LocalTextConfiguration.current.overflow,
    minTextSize: TextUnit = 12.sp,
    contentAlignment: Alignment = Alignment.Center,
    fadeInMillis: Int = 250, // Slower fade for a premium feel
    scaleDownOnly: Boolean = true
) {
    ScalableText(
        text = AnnotatedString(text),
        modifier = modifier,
        textModifier = textModifier,
        color = color,
        style = style,
        overflow = overflow,
        minTextSize = minTextSize,
        contentAlignment = contentAlignment,
        fadeInMillis = fadeInMillis,
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
    overflow: TextOverflow = LocalTextConfiguration.current.overflow,
    minTextSize: TextUnit = 12.sp,
    contentAlignment: Alignment = Alignment.Center,
    fadeInMillis: Int = 250, // Slower fade for a premium feel
    scaleDownOnly: Boolean = true
) {
    val isInspectionMode = LocalInspectionMode.current

    val measurer = rememberTextMeasurer()
    val density = LocalDensity.current
    val fontFamilyResolver = LocalFontFamilyResolver.current
    val supportsNativeBoundsText = remember(text) {
        text.spanStyles.isEmpty() && text.paragraphStyles.isEmpty()
    }

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
    val resolvedTypeface = if (supportsNativeBoundsText) {
        fontFamilyResolver.resolve(
            fontFamily = baseStyle.fontFamily,
            fontWeight = baseStyle.fontWeight ?: FontWeight.Normal,
            fontStyle = baseStyle.fontStyle ?: FontStyle.Normal,
            fontSynthesis = baseStyle.fontSynthesis ?: FontSynthesis.All
        ).value as? Typeface
    } else {
        null
    }

    BoxWithConstraints(modifier = modifier, contentAlignment = contentAlignment) {
        val maxWidthPx = with(density) { maxWidth.toPx() }
        val maxHeightPx = with(density) { maxHeight.toPx() }

        // Safety check to ensure layout is actually ready before we calculate
        val isLayoutReady = maxWidthPx > 1 && maxHeightPx > 1

        // 1. Calculate the ideal font size (Linear Math - Fast O(1))
        val fittedSize = remember(
            text,
            maxWidthPx,
            maxHeightPx,
            baseStyle,
            minTextSize,
            scaleDownOnly,
            supportsNativeBoundsText
        ) {
            if (!isLayoutReady) return@remember minTextSize

            val baseFontSize = baseStyle.fontSize
            val upperBound = if (scaleDownOnly) baseFontSize
            else if (baseFontSize.value >= 32f) baseFontSize else 32.sp

            val metrics = if (supportsNativeBoundsText) {
                measureNativeTextMetrics(
                    text = text.text,
                    style = baseStyle,
                    fontSize = upperBound,
                    density = density,
                    typeface = resolvedTypeface
                )
            } else {
                val result = measurer.measure(
                    text = text,
                    style = baseStyle.copy(fontSize = upperBound),
                    maxLines = 1,
                    softWrap = false
                )
                NativeTextMetrics(
                    widthPx = result.size.width.toFloat(),
                    heightPx = result.size.height.toFloat(),
                    leftPx = 0
                )
            }

            // Calculate ratios for both dimensions
            val widthRatio = if (metrics.widthPx > 0) maxWidthPx / metrics.widthPx else 1f
            val heightRatio = if (metrics.heightPx > 0) maxHeightPx / metrics.heightPx else 1f

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

        val fittedTextLayout = remember(text, fittedSize, baseStyle, supportsNativeBoundsText) {
            if (supportsNativeBoundsText) {
                null
            } else {
                measurer.measure(
                    text = text,
                    style = baseStyle.copy(fontSize = fittedSize),
                    maxLines = 1,
                    softWrap = false
                )
            }
        }

        // 3. Handle the Initial Fade-In
        val alphaAnim = remember { Animatable(0f) }

        // Trigger ONLY on initial composition (Unit key), not when text changes
        LaunchedEffect(Unit) {
            if (fadeInMillis > 0) {
                alphaAnim.snapTo(0f)
                // Small delay ensures layout is stable before making it visible
                delay(50)
                alphaAnim.animateTo(
                    targetValue = 1f,
                    animationSpec = tween(
                        durationMillis = fadeInMillis,
                        easing = LinearOutSlowInEasing
                    )
                )
            } else {
                alphaAnim.snapTo(1f)
            }
        }

        val baseModifier = if(isInspectionMode){
            textModifier
        }else {
            textModifier.graphicsLayer {
                this.alpha = if (isLayoutReady) alphaAnim.value else 0f
            }
        }

        if (supportsNativeBoundsText) {
            AndroidView(
                modifier = baseModifier,
                factory = { viewContext ->
                    BoundsAwareTextView(viewContext).apply {
                        layoutParams = ViewGroup.LayoutParams(
                            ViewGroup.LayoutParams.WRAP_CONTENT,
                            ViewGroup.LayoutParams.WRAP_CONTENT
                        )
                        includeFontPadding = false
                        isSingleLine = true
                        setPadding(0, 0, 0, 0)
                        enableBoundsAwareWidthIfSupported()
                    }
                },
                update = { textView ->
                    textView.text = text.text
                    textView.setTextColor(color.toArgb())
                    textView.setTextSize(TypedValue.COMPLEX_UNIT_SP, fittedSize.value)
                    textView.gravity = Gravity.CENTER_HORIZONTAL or Gravity.CENTER_VERTICAL
                    textView.ellipsize = overflow.toAndroidEllipsize()
                    textView.typeface = resolvedTypeface ?: defaultComposeTypeface(baseStyle)
                    textView.letterSpacing = resolveLetterSpacing(
                        letterSpacing = baseStyle.letterSpacing,
                        fontSize = fittedSize,
                        density = density
                    )
                    textView.enableBoundsAwareWidthIfSupported()
                    textView.requestLayout()
                }
            )
        } else {
            val safeTextLayout = fittedTextLayout ?: return@BoxWithConstraints
            val fittedTextMetrics = remember(text, safeTextLayout) {
                computeVisibleTextMetrics(text = text, layout = safeTextLayout)
            }

            SubcomposeLayout(modifier = baseModifier) { constraints ->
                val exactWidthPx = fittedTextMetrics.visibleWidthPx
                    .coerceIn(constraints.minWidth, constraints.maxWidth)
                val textLayoutWidthPx = safeTextLayout.size.width
                    .coerceIn(exactWidthPx, constraints.maxWidth)

                val textPlaceable = subcompose("scalableText") {
                    Text(
                        text = text,
                        style = baseStyle.copy(fontSize = fittedSize),
                        color = color,
                        maxLines = 1,
                        textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                        overflow = overflow
                    )
                }.first().measure(
                    Constraints(
                        minWidth = textLayoutWidthPx,
                        maxWidth = textLayoutWidthPx,
                        minHeight = 0,
                        maxHeight = constraints.maxHeight
                    )
                )

                layout(exactWidthPx, textPlaceable.height) {
                    textPlaceable.placeRelative(-fittedTextMetrics.leftInsetPx, 0)
                }
            }
        }
    }
}

private data class VisibleTextMetrics(
    val visibleWidthPx: Int,
    val leftInsetPx: Int
)

private fun computeVisibleTextMetrics(
    text: AnnotatedString,
    layout: TextLayoutResult
): VisibleTextMetrics {
    if (text.isEmpty()) {
        return VisibleTextMetrics(
            visibleWidthPx = layout.size.width,
            leftInsetPx = 0
        )
    }

    var left = Float.POSITIVE_INFINITY
    var right = Float.NEGATIVE_INFINITY

    text.forEachIndexed { index, char ->
        if (!char.isWhitespace()) {
            val bounds = layout.getBoundingBox(index)
            left = min(left, bounds.left)
            right = maxOf(right, bounds.right)
        }
    }

    if (!left.isFinite() || !right.isFinite() || right <= left) {
        return VisibleTextMetrics(
            visibleWidthPx = layout.size.width,
            leftInsetPx = 0
        )
    }

    return VisibleTextMetrics(
        visibleWidthPx = ceil(right - left).toInt().coerceAtLeast(1),
        leftInsetPx = left.toInt()
    )
}

private data class NativeTextMetrics(
    val widthPx: Float,
    val heightPx: Float,
    val leftPx: Int
)

private fun measureNativeTextMetrics(
    text: String,
    style: TextStyle,
    fontSize: TextUnit,
    density: Density,
    typeface: Typeface?
): NativeTextMetrics {
    val paint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        applyComposeStyle(
            style = style,
            fontSize = fontSize,
            density = density,
            typeface = typeface
        )
    }
    val bounds = Rect()
    if (text.isNotEmpty()) {
        paint.getTextBounds(text, 0, text.length, bounds)
    }

    val metrics = paint.fontMetrics
    val heightPx = (metrics.descent - metrics.ascent).coerceAtLeast(1f)
    val widthPx = bounds.width().toFloat().coerceAtLeast(0f)

    return NativeTextMetrics(
        widthPx = widthPx,
        heightPx = heightPx,
        leftPx = bounds.left
    )
}

private fun TextPaint.applyComposeStyle(
    style: TextStyle,
    fontSize: TextUnit,
    density: Density,
    typeface: Typeface?
) {
    textSize = with(density) { fontSize.toPx() }
    this.typeface = typeface ?: defaultComposeTypeface(style)
    letterSpacing = resolveLetterSpacing(
        letterSpacing = style.letterSpacing,
        fontSize = fontSize,
        density = density
    )
}

private fun defaultComposeTypeface(style: TextStyle): Typeface {
    val isBold = (style.fontWeight ?: FontWeight.Normal) >= FontWeight.SemiBold
    val isItalic = style.fontStyle == FontStyle.Italic
    val typefaceStyle = when {
        isBold && isItalic -> Typeface.BOLD_ITALIC
        isBold -> Typeface.BOLD
        isItalic -> Typeface.ITALIC
        else -> Typeface.NORMAL
    }
    return Typeface.create(Typeface.DEFAULT, typefaceStyle)
}

private fun resolveLetterSpacing(
    letterSpacing: TextUnit,
    fontSize: TextUnit,
    density: Density
): Float {
    return when (letterSpacing.type) {
        TextUnitType.Em -> letterSpacing.value
        TextUnitType.Sp -> {
            val fontSizePx = with(density) { fontSize.toPx() }
            if (fontSizePx == 0f) 0f else with(density) { letterSpacing.toPx() } / fontSizePx
        }
        else -> 0f
    }
}

private fun TextOverflow.toAndroidEllipsize(): TextUtils.TruncateAt? {
    return when (this) {
        TextOverflow.Ellipsis -> TextUtils.TruncateAt.END
        TextOverflow.StartEllipsis -> TextUtils.TruncateAt.START
        TextOverflow.MiddleEllipsis -> TextUtils.TruncateAt.MIDDLE
        else -> null
    }
}

private class BoundsAwareTextView(context: Context) : AppCompatTextView(context) {
    private val textBounds = Rect()

    override fun onDraw(canvas: Canvas) {
        val currentText = text?.toString().orEmpty()
        val currentLayout = layout
        if (currentText.isEmpty() || currentLayout == null) {
            super.onDraw(canvas)
            return
        }

        paint.getTextBounds(currentText, 0, currentText.length, textBounds)
        if (textBounds.isEmpty) {
            super.onDraw(canvas)
            return
        }

        val contentTop = compoundPaddingTop.toFloat()
        val contentHeight = (height - compoundPaddingTop - compoundPaddingBottom).toFloat()
        val baseline = compoundPaddingTop + currentLayout.getLineBaseline(0).toFloat()
        val glyphTop = baseline + textBounds.top
        val desiredGlyphTop = contentTop + ((contentHeight - textBounds.height()) / 2f)
        val verticalShift = desiredGlyphTop - glyphTop

        val saveCount = canvas.save()
        canvas.translate(0f, verticalShift)
        super.onDraw(canvas)
        canvas.restoreToCount(saveCount)
    }
}

private fun BoundsAwareTextView.enableBoundsAwareWidthIfSupported() {
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.VANILLA_ICE_CREAM) {
        setUseBoundsForWidth(true)
        setShiftDrawingOffsetForStartOverhang(true)
    }
}
