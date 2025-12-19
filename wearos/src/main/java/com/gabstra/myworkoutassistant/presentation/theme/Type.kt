package com.gabstra.myworkoutassistant.presentation.theme

import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.googlefonts.Font
import androidx.compose.ui.text.googlefonts.GoogleFont
import androidx.wear.compose.material3.Typography
import com.gabstra.myworkoutassistant.R

val provider = GoogleFont.Provider(
    providerAuthority = "com.google.android.gms.fonts",
    providerPackage = "com.google.android.gms",
    certificates = R.array.com_google_android_gms_fonts_certs
)

val bodyFontFamily = FontFamily(
    Font(
        googleFont = GoogleFont("Roboto"),
        fontProvider = provider,
    )
)

private fun TextStyle.withTabularNumbers(): TextStyle =
    copy(fontFeatureSettings = "tnum")



// Material 3 Wear typography with tabular numbers applied to all roles
val baseline = Typography().let { base ->
    Typography(
        arcLarge = base.arcLarge,
        arcMedium = base.arcMedium,
        arcSmall = base.arcSmall,
        displayLarge = base.displayLarge.withTabularNumbers(),
        displayMedium = base.displayMedium.withTabularNumbers(),
        displaySmall = base.displaySmall.withTabularNumbers(),
        titleLarge = base.titleLarge.withTabularNumbers(),
        titleMedium = base.titleMedium.withTabularNumbers(),
        titleSmall = base.titleSmall.withTabularNumbers(),
        bodyLarge = base.bodyLarge.withTabularNumbers(),
        bodyMedium = base.bodyMedium.withTabularNumbers(),
        bodySmall = base.bodySmall.withTabularNumbers(),
        bodyExtraSmall = base.bodyExtraSmall.withTabularNumbers(),
        labelLarge = base.labelLarge.withTabularNumbers(),
        labelMedium = base.labelMedium.withTabularNumbers(),
        labelSmall = base.labelSmall.withTabularNumbers(),
        numeralExtraLarge = base.numeralExtraLarge.withTabularNumbers(),
        numeralLarge = base.numeralLarge.withTabularNumbers(),
        numeralMedium = base.numeralMedium.withTabularNumbers(),
        numeralSmall = base.numeralSmall.withTabularNumbers(),
        numeralExtraSmall = base.numeralExtraSmall.withTabularNumbers(),
    )
}

/*
val AppTypography = Typography(
    displayLarge = baseline.displayLarge.copy(fontFamily = displayFontFamily),
    displayMedium = baseline.displayMedium.copy(fontFamily = displayFontFamily),
    displaySmall = baseline.displaySmall.copy(fontFamily = displayFontFamily),
    headlineLarge = baseline.headlineLarge.copy(fontFamily = displayFontFamily),
    headlineMedium = baseline.headlineMedium.copy(fontFamily = displayFontFamily),
    headlineSmall = baseline.headlineSmall.copy(fontFamily = displayFontFamily),
    titleLarge = baseline.titleLarge.copy(fontFamily = displayFontFamily),
    titleMedium = baseline.titleMedium.copy(fontFamily = displayFontFamily),
    titleSmall = baseline.titleSmall.copy(fontFamily = displayFontFamily),
    bodyLarge = baseline.bodyLarge.copy(fontFamily = bodyFontFamily),
    bodyMedium = baseline.bodyMedium.copy(fontFamily = bodyFontFamily),
    bodySmall = baseline.bodySmall.copy(fontFamily = bodyFontFamily),
    labelLarge = baseline.labelLarge.copy(fontFamily = bodyFontFamily),
    labelMedium = baseline.labelMedium.copy(fontFamily = bodyFontFamily),
    labelSmall = baseline.labelSmall.copy(fontFamily = bodyFontFamily),
)
*/