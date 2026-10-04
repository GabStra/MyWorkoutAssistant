package com.gabstra.myworkoutassistant.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.font.FontWeight
import com.gabstra.myworkoutassistant.shared.AppFontFamily

// Material 3 typography on the shared bundled Roboto, matching the wear app.
// Sub-header/label roles are Bold so secondary text differentiates by weight
// rather than by a dim gray.
val Typography = Typography().let { base ->
    Typography(
        displayLarge = base.displayLarge.copy(fontFamily = AppFontFamily),
        displayMedium = base.displayMedium.copy(fontFamily = AppFontFamily),
        displaySmall = base.displaySmall.copy(fontFamily = AppFontFamily),
        headlineLarge = base.headlineLarge.copy(fontFamily = AppFontFamily),
        headlineMedium = base.headlineMedium.copy(fontFamily = AppFontFamily),
        headlineSmall = base.headlineSmall.copy(fontFamily = AppFontFamily),
        titleLarge = base.titleLarge.copy(fontFamily = AppFontFamily),
        titleMedium = base.titleMedium.copy(fontFamily = AppFontFamily),
        titleSmall = base.titleSmall.copy(fontFamily = AppFontFamily),
        bodyLarge = base.bodyLarge.copy(fontFamily = AppFontFamily),
        bodyMedium = base.bodyMedium.copy(fontFamily = AppFontFamily),
        bodySmall = base.bodySmall.copy(fontFamily = AppFontFamily),
        labelLarge = base.labelLarge.copy(fontFamily = AppFontFamily),
        labelMedium = base.labelMedium.copy(fontFamily = AppFontFamily, fontWeight = FontWeight.Bold),
        labelSmall = base.labelSmall.copy(fontFamily = AppFontFamily, fontWeight = FontWeight.Bold),
    )
}
