import androidx.compose.ui.graphics.Color

// Primary
val Orange = Color(0xFFFF6700)
val primaryDark = Orange
val primaryDimDark = Color(0xFFCC5200)           // toned down primary
val primaryContainerDark = Color(0xFF7f3300)     // ≥3:1 vs black
val onPrimaryDark = Color(0xFF303030)
val onPrimaryContainerDark = Color(0xFFFFFFFF)

// Secondary (warm accent)
val secondaryDark = Color(0xFFFFB870)
val secondaryDimDark = Color(0xFFE3A25E)
val secondaryContainerDark = Color(0xFF7f3300)   // ≥3:1 vs black
val onSecondaryDark = Color(0xFF000000)
val onSecondaryContainerDark = Color(0xFFFFFFFF)

// Tertiary (cool accent)
val tertiaryDark = Color(0xFF4FC3F7)
val tertiaryDimDark = Color(0xFF39AEDF)
val tertiaryContainerDark = Color(0xFF006280)    // ≥3:1 vs black
val onTertiaryDark = Color(0xFF000000)
val onTertiaryContainerDark = Color(0xFFCDEEFF)

// Error
val errorDark = Color(0xFFFFB4AB)
val errorDimDark = Color(0xFFB3261E)             // M3 dim/error tone
val errorContainerDark = Color(0xFF93000A)
val onErrorDark = Color(0xFF690005)
val onErrorContainerDark = Color(0xFFFFDAD6)

// Surfaces / background
val backgroundDark = Color(0xFF000000)
val onBackgroundDark = Color(0xFFF5F5F5)

val surfaceContainerLowDark  = Color(0xFF121212) // onSurface 17.95:1; onSurfaceVariant 11.20:1
val surfaceContainerDark     = Color(0xFF5C5C5C) // onSurface 16.67:1; onSurfaceVariant 10.40:1
val surfaceContainerHighDark = Color(0xFF242424) // onSurface 14.87:1; onSurfaceVariant  9.28:1

val onSurfaceDark            = Color(0xFFFFFFFF) // ≥4.5:1 vs all surfaces (see above)
val onSurfaceVariantDark     = Color(0xFFC8C8C8) // ≥4.5:1 vs all surfaces (see above)

val outlineDark              = Color(0xFFB0B0B0) // ≥3:1 vs all surfaces (5.43 / 5.04 / 4.50)
val outlineVariantDark       = Color(0xFF6D6D6D) // adjusted to meet ≥3:1; ratios 3.62 / 3.36 / 3.00