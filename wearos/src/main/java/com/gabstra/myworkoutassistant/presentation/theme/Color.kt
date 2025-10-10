import androidx.compose.ui.graphics.Color

// Primary seed
val Orange = Color(0xFFFF6700)

// Normal-contrast dark palette (WCAG AA on black bg)
val primaryDark = Orange                         // 7.19:1 vs black
val onPrimaryDark = Color(0xFF000000)            // 7.19:1 on primary

// ≥3:1 vs black, and on* text ≥4.5:1
val primaryContainerDark = Color(0xFF994000)     // 3.09:1 vs black
val onPrimaryContainerDark = Color(0xFFFFE7D6)   // 5.72:1 on primaryContainer

// Secondary tuned for split-complement harmony with Orange (#FF6700)
val secondaryDark = Color(0xFFFF995E)            // 9.97:1 vs black
val onSecondaryDark = Color(0xFF000000)          // 9.97:1 on secondary
val secondaryContainerDark = Color(0xFF8F4A00)   // 3.15:1 vs black
val onSecondaryContainerDark = Color(0xFFFFE6CC)

val tertiaryDark = Color(0xFF4FC3F7)             // 10.48:1 vs black
val onTertiaryDark = Color(0xFF000000)           // 10.48:1 on tertiary
val tertiaryContainerDark = Color(0xFF006280)    // 3.06:1 vs black
val onTertiaryContainerDark = Color(0xFFCDEEFF)  // 5.65:1 on tertiaryContainer

val errorDark = Color(0xFFFFB4AB)
val onErrorDark = Color(0xFF690005)
// FIXED to meet ≥3:1 against black and ≥4.5:1 with onErrorContainer
val errorContainerDark = Color(0xFFC00012)       // 3.25:1 vs black
val onErrorContainerDark = Color(0xFFFFDAD6)     // 5.00:1 on errorContainer

val backgroundDark = Color(0xFF000000)
val onBackgroundDark = Color(0xFFF2F2F2)
val surfaceDark = Color(0xFF141414)
val onSurfaceDark = Color(0xFFF2F2F2)

val surfaceVariantDark = Color(0xFF2A2A2A)
val onSurfaceVariantDark = Color(0xFFDDDDDD)
val outlineDark = Color(0xFF7A7A7A)
// visible dividers/borders on black (≥3:1)
val outlineVariantDark = Color(0xFF5A5A5A)       // 3.04:1 vs black

val scrimDark = Color(0xFF000000)

val inverseSurfaceDark = Color(0xFFE6E6E6)
val inverseOnSurfaceDark = Color(0xFF1A1A1A)
val inversePrimaryDark = Color(0xFF9E3F00)       // 5.32:1 vs inverseSurface

val surfaceDimDark = Color(0xFF0E0E0E)
val surfaceBrightDark = Color(0xFF262626)
val surfaceContainerLowestDark = Color(0xFF0A0A0A)
val surfaceContainerLowDark = Color(0xFF141414)
val surfaceContainerDark = Color(0xFF161616)
val surfaceContainerHighDark = Color(0xFF1B1B1B)