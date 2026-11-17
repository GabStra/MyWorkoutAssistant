package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.LocalTextStyle
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.presentation.theme.asNumeral

/**
 * Label and its value with a real gap between them: the label keeps [style], the value
 * renders [style]'s numeral variant (same size, tabular, tight), and [suffix] (e.g. " reps")
 * trails the value in the label style.
 *
 * When the parts do not fit the available width side by side, they stack vertically
 * (label above value) instead of clipping.
 */
@Composable
fun LabeledNumericValue(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
    style: TextStyle = LocalTextStyle.current,
    // Defaults to the label style's numeral variant; pass a style to override.
    valueStyle: TextStyle = style.asNumeral(),
    color: Color = Color.Unspecified,
    gap: Dp = 3.dp,
    suffix: String = "",
) {
    val measurer = rememberTextMeasurer()
    val density = LocalDensity.current
    val labelWidth = measurer.measure(AnnotatedString(label), style, maxLines = 1, softWrap = false).size.width
    val valueWidth = measurer.measure(AnnotatedString(value), valueStyle, maxLines = 1, softWrap = false).size.width
    val suffixWidth = if (suffix.isEmpty()) {
        0
    } else {
        measurer.measure(AnnotatedString(suffix), style, maxLines = 1, softWrap = false).size.width
    }
    val gapPx = with(density) { gap.toPx() }
    val parts = 2 + if (suffix.isEmpty()) 0 else 1
    val requiredWidth = labelWidth + valueWidth + suffixWidth + gapPx * (parts - 1)

    BoxWithConstraints(modifier = modifier) {
        val fitsInRow = constraints.maxWidth == Constraints.Infinity ||
            constraints.maxWidth >= requiredWidth

        if (fitsInRow) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(gap, Alignment.CenterHorizontally),
            ) {
                LabelText(label, style, color)
                ValueText(value, valueStyle, color)
                if (suffix.isNotEmpty()) LabelText(suffix, style, color)
            }
        } else {
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(gap / 2),
            ) {
                LabelText(label, style, color)
                ValueText(value, valueStyle, color)
                if (suffix.isNotEmpty()) LabelText(suffix, style, color)
            }
        }
    }
}

@Composable
private fun LabelText(text: String, style: TextStyle, color: Color) {
    Text(text = text, style = style, color = color, maxLines = 1, softWrap = false)
}

@Composable
private fun ValueText(text: String, style: TextStyle, color: Color) {
    Text(text = text, style = style, color = color, maxLines = 1, softWrap = false)
}
