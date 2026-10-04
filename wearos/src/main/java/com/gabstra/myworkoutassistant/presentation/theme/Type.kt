package com.gabstra.myworkoutassistant.presentation.theme

import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.wear.compose.material3.Typography
import com.gabstra.myworkoutassistant.shared.AppFontFamily

private fun TextStyle.withTabularNumbers(): TextStyle =
    copy(fontFeatureSettings = "tnum")

private fun TextStyle.withAppFont(weight: FontWeight? = null): TextStyle =
    copy(fontFamily = AppFontFamily, fontWeight = weight ?: this.fontWeight)

// Material 3 Wear typography on the shared bundled Roboto, matching the mobile
// app. Tabular numbers apply to all roles; sub-header/label roles are Bold so
// secondary text differentiates by weight rather than by a dim gray.
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
        labelMedium = base.labelMedium.withAppFont(FontWeight.Bold).withTabularNumbers(),
        labelSmall = base.labelSmall.withAppFont(FontWeight.Bold).withTabularNumbers(),
        numeralExtraLarge = base.numeralExtraLarge.withAppFont().withTabularNumbers(),
        numeralLarge = base.numeralLarge.withAppFont().withTabularNumbers(),
        numeralMedium = base.numeralMedium.withAppFont().withTabularNumbers(),
        numeralSmall = base.numeralSmall.withAppFont().withTabularNumbers(),
        numeralExtraSmall = base.numeralExtraSmall.withAppFont().withTabularNumbers(),
    )
}
