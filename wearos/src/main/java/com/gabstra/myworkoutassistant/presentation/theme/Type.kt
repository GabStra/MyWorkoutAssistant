package com.gabstra.myworkoutassistant.presentation.theme

import androidx.compose.runtime.Composable
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.LineHeightStyle
import androidx.compose.ui.unit.sp
import androidx.wear.compose.material3.Typography
import com.gabstra.myworkoutassistant.composables.NumericLineHeightScale
import com.gabstra.myworkoutassistant.shared.AppFontFamily

private fun TextStyle.withTabularNumbers(): TextStyle =
    copy(fontFeatureSettings = "tnum")

private fun TextStyle.withAppFont(weight: FontWeight? = null): TextStyle =
    copy(fontFamily = AppFontFamily, fontWeight = weight ?: this.fontWeight)

// Numeric roles render single-line digits; Roboto's ascent/descent still add ~0.3em of
// air around cap-height digits at lineHeight = fontSize, so clamp the line box below the
// glyph box (0.85em) and center the ink — digits have no descenders, so nothing clips.
private fun TextStyle.withTightNumerals(): TextStyle =
    copy(
        lineHeight = fontSize * NumericLineHeightScale,
        lineHeightStyle = LineHeightStyle(
            alignment = LineHeightStyle.Alignment.Center,
            trim = LineHeightStyle.Trim.Both,
        ),
    )

// Material 3 Wear typography on the shared bundled Roboto, matching the mobile
// app. Tabular numbers apply to all roles; small labels use regular weight
// to keep supporting text readable on the watch.
val baseline = Typography().let { base ->
    Typography(
        arcLarge = base.arcLarge,
        arcMedium = base.arcMedium,
        arcSmall = base.arcSmall,
        displayLarge = base.displayLarge.withAppFont().withTabularNumbers(),
        displayMedium = base.displayMedium.withAppFont().withTabularNumbers(),
        displaySmall = base.displaySmall.withAppFont().withTabularNumbers(),
        titleLarge = base.titleLarge.withAppFont().withTabularNumbers(),
        titleMedium = base.titleMedium.withAppFont().withTabularNumbers(),
        titleSmall = base.titleSmall.withAppFont().withTabularNumbers(),
        bodyLarge = base.bodyLarge.withAppFont().withTabularNumbers(),
        bodyMedium = base.bodyMedium.withAppFont().withTabularNumbers(),
        bodySmall = base.bodySmall.withAppFont().withTabularNumbers(),
        bodyExtraSmall = base.bodyExtraSmall.withAppFont().withTabularNumbers(),
        labelLarge = base.labelLarge.withAppFont().withTabularNumbers(),
        labelMedium = base.labelMedium.withAppFont(FontWeight.Normal).withTabularNumbers(),
        labelSmall = base.labelSmall.withAppFont(FontWeight.Normal).withTabularNumbers(),
        numeralExtraLarge = base.numeralExtraLarge.withAppFont().withTabularNumbers().withTightNumerals(),
        numeralLarge = base.numeralLarge.withAppFont().withTabularNumbers().withTightNumerals(),
        numeralMedium = base.numeralMedium.withAppFont().withTabularNumbers().withTightNumerals(),
        numeralSmall = base.numeralSmall.withAppFont().withTabularNumbers().withTightNumerals(),
        numeralExtraSmall = base.numeralExtraSmall.withAppFont().withTabularNumbers().withTightNumerals(),
    )
}

/**
 * Numeric role below numeralExtraSmall (24sp) for compact chrome — clock, battery,
 * counters, secondary readouts. Same numeric look at label size; the numeral roles
 * in [baseline] start at 24sp, which dwarfs those rows.
 */
val Typography.numeralMicro: TextStyle
    @Composable get() = numeralExtraSmall.copy(
        fontSize = 15.sp,
        lineHeight = 15.sp * NumericLineHeightScale,
    )

/**
 * Numeric variant of any text style: identical size and family, tabular digits and the
 * numeral weight, with the tight line box. Use for values embedded in a label line so the
 * value matches its label's size (e.g. bodyExtraSmall → 10sp numerals).
 */
fun TextStyle.asNumeral(): TextStyle = copy(
    fontFeatureSettings = "tnum",
    fontWeight = FontWeight(550),
    lineHeight = fontSize * NumericLineHeightScale,
    lineHeightStyle = LineHeightStyle(
        alignment = LineHeightStyle.Alignment.Center,
        trim = LineHeightStyle.Trim.Both,
    ),
)
