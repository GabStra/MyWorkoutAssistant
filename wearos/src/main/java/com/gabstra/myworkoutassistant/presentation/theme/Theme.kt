package com.gabstra.myworkoutassistant.presentation.theme

import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.ui.graphics.Color
import androidx.wear.compose.material3.ColorScheme
import androidx.wear.compose.material3.MaterialTheme
import backgroundDark
import errorContainerDark
import errorDark
import onBackgroundDark
import onErrorContainerDark
import onErrorDark
import onPrimaryContainerDark
import onPrimaryDark
import onSecondaryContainerDark
import onSecondaryDark
import onSurfaceVariantDark
import onTertiaryContainerDark
import onTertiaryDark
import outlineDark
import outlineVariantDark
import primaryContainerDark
import primaryDark
import secondaryContainerDark
import secondaryDark
import tertiaryContainerDark
import tertiaryDark


val normalDarkColorScheme = ColorScheme(
    primary = primaryDark,
    onPrimary = onPrimaryDark,
    primaryContainer = primaryContainerDark,
    onPrimaryContainer = onPrimaryContainerDark,
    secondary = secondaryDark,
    onSecondary = onSecondaryDark,
    secondaryContainer = secondaryContainerDark,
    onSecondaryContainer = onSecondaryContainerDark,
    tertiary = tertiaryDark,
    onTertiary = onTertiaryDark,
    tertiaryContainer = tertiaryContainerDark,
    onTertiaryContainer = onTertiaryContainerDark,
    error = errorDark,
    onError = onErrorDark,
    errorContainer = errorContainerDark,
    onErrorContainer = onErrorContainerDark,
    background = backgroundDark,
    onBackground = onBackgroundDark,
    onSurface = onSecondaryContainerDark,
    onSurfaceVariant = onSurfaceVariantDark,
    outline = outlineDark,
    outlineVariant = outlineVariantDark,
    surfaceContainerLow = secondaryContainerDark,
    surfaceContainer = secondaryContainerDark,
    surfaceContainerHigh = secondaryContainerDark,
)

@Immutable
data class ColorFamily(
    val color: Color,
    val onColor: Color,
    val colorContainer: Color,
    val onColorContainer: Color
)

val unspecified_scheme = ColorFamily(
    Color.Unspecified, Color.Unspecified, Color.Unspecified, Color.Unspecified
)

@Composable
fun MyWorkoutAssistantTheme(
    content: @Composable () -> Unit
) {
    CompositionLocalProvider(
        androidx.compose.material3.LocalTonalElevationEnabled provides false
    ) {
        MaterialTheme(
            colorScheme = normalDarkColorScheme,
            typography = baseline,
            content = content
        )
    }
}