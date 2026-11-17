package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.wrapContentHeight
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.wear.compose.material3.Text

/**
 * Single-line numeric text whose layout hugs the digit ink.
 *
 * A plain Text always reserves the font's ascent+descent box — Roboto is 1.172em — and
 * LineHeightStyle.Trim only removes leading outside those metrics, so values carried
 * ~0.46em of dead air no matter how small lineHeight got. The measured height is clamped
 * to 0.85em (digit cap is 0.711em) and the glyphs centre inside it; the text paints
 * slightly outside the box, which is invisible and does not add layout space.
 */
@Composable
fun TightNumericText(
    text: String,
    style: TextStyle,
    modifier: Modifier = Modifier,
    color: Color = Color.Unspecified,
    textAlign: TextAlign? = null,
) = TightNumericText(
    text = AnnotatedString(text),
    style = style,
    modifier = modifier,
    color = color,
    textAlign = textAlign,
)

/** The numeral roles in presentation/theme/Type.kt carry this exact line-height scale. */
internal const val NumericLineHeightScale = 0.9f

/** True for the theme's numeral roles (and any .copy() of them that keeps the metrics). */
internal fun TextStyle.isTightNumericStyle(): Boolean =
    fontSize.isSp && lineHeight == fontSize * NumericLineHeightScale

@Composable
fun TightNumericText(
    text: AnnotatedString,
    style: TextStyle,
    modifier: Modifier = Modifier,
    color: Color = Color.Unspecified,
    textAlign: TextAlign? = null,
) {
    val height = with(LocalDensity.current) { (style.fontSize * NumericLineHeightScale).toDp() }
    Box(
        modifier = modifier.height(height),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = text,
            style = style,
            color = color,
            maxLines = 1,
            softWrap = false,
            textAlign = textAlign,
            // Unbounded measurement: the Text keeps its natural (taller) box and paints
            // outside the clamped parent instead of being measured to fit and clipped.
            modifier = Modifier.wrapContentHeight(unbounded = true),
        )
    }
}
