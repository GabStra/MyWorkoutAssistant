import androidx.compose.ui.graphics.Color

// Primary seed
val Orange = Color(0xFFFF6700)

// Normal-contrast dark palette (WCAG AA on black bg)
val primaryDark = Orange
val onPrimaryDark = Color(0xFF000000)

// UPDATED: ≥3:1 vs black, and on* text ≥4.5:1
val primaryContainerDark = Color(0xFF994000)   // 3.09:1 vs #000; 5.72:1 with onPrimaryContainerDark
val onPrimaryContainerDark = Color(0xFFFFE7D6)

val secondaryDark = Color(0xFFFFB870)
val onSecondaryDark = Color(0xFF000000)
val secondaryContainerDark = Color(0xFF8F4900) // 3.12:1 vs #000; 5.59:1 with onSecondaryContainerDark
val onSecondaryContainerDark = Color(0xFFFFE6CC)

val tertiaryDark = Color(0xFF4FC3F7)
val onTertiaryDark = Color(0xFF000000)
val tertiaryContainerDark = Color(0xFF006280)  // 3.06:1 vs #000; 5.65:1 with onTertiaryContainerDark
val onTertiaryContainerDark = Color(0xFFCDEEFF)

val errorDark = Color(0xFFFFB4AB)
val onErrorDark = Color(0xFF690005)
val errorContainerDark = Color(0xFF93000A)
val onErrorContainerDark = Color(0xFFFFDAD6)

val backgroundDark = Color(0xFF000000)
val onBackgroundDark = Color(0xFFF2F2F2)
val surfaceDark = Color(0xFF141414)
val onSurfaceDark = Color(0xFFF2F2F2)

val surfaceVariantDark = Color(0xFF2A2A2A)
val onSurfaceVariantDark = Color(0xFFDDDDDD)
val outlineDark = Color(0xFF7A7A7A)
// ensure visible dividers/borders on black (≥3:1)
val outlineVariantDark = Color(0xFF5A5A5A)

val scrimDark = Color(0xFF000000)

val inverseSurfaceDark = Color(0xFFE6E6E6)
val inverseOnSurfaceDark = Color(0xFF1A1A1A)
val inversePrimaryDark = Color(0xFF9E3F00)

val surfaceDimDark = Color(0xFF0E0E0E)
val surfaceBrightDark = Color(0xFF262626)
val surfaceContainerLowestDark = Color(0xFF0A0A0A)
val surfaceContainerLowDark = Color(0xFF141414)
val surfaceContainerDark = Color(0xFF161616)
val surfaceContainerHighDark = Color(0xFF1B1B1B)
val surfaceContainerHighestDark = Color(0xFF212121)