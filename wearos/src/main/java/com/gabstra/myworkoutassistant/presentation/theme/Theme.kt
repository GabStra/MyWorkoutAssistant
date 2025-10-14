package com.gabstra.myworkoutassistant.presentation.theme

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.wear.compose.material3.ColorScheme
import androidx.wear.compose.material3.MaterialTheme
import backgroundDark
import errorContainerDark
import errorDark
import errorDimDark
import onBackgroundDark
import onErrorContainerDark
import onErrorDark
import onPrimaryContainerDark
import onPrimaryDark
import onSecondaryContainerDark
import onSecondaryDark
import onSurfaceDark
import onSurfaceVariantDark
import onTertiaryContainerDark
import onTertiaryDark
import outlineDark
import outlineVariantDark
import primaryContainerDark
import primaryDark
import primaryDimDark
import secondaryContainerDark
import secondaryDark
import secondaryDimDark
import surfaceContainerDark
import surfaceContainerHighDark
import surfaceContainerLowDark
import tertiaryContainerDark
import tertiaryDark
import tertiaryDimDark

val darkScheme = ColorScheme(
    primary = primaryDark,
    primaryDim = primaryDimDark,
    primaryContainer = primaryContainerDark,
    onPrimary = onPrimaryDark,
    onPrimaryContainer = onPrimaryContainerDark,

    secondary = secondaryDark,
    secondaryDim = secondaryDimDark,
    secondaryContainer = secondaryContainerDark,
    onSecondary = onSecondaryDark,
    onSecondaryContainer = onSecondaryContainerDark,

    tertiary = tertiaryDark,
    tertiaryDim = tertiaryDimDark,
    tertiaryContainer = tertiaryContainerDark,
    onTertiary = onTertiaryDark,
    onTertiaryContainer = onTertiaryContainerDark,

    surfaceContainerLow = surfaceContainerLowDark,
    surfaceContainer = surfaceContainerDark,
    surfaceContainerHigh = surfaceContainerHighDark,
    onSurface = onSurfaceDark,
    onSurfaceVariant = onSurfaceVariantDark,
    outline = outlineDark,
    outlineVariant = outlineVariantDark,

    background = backgroundDark,
    onBackground = onBackgroundDark,

    error = errorDark,
    errorDim = errorDimDark,
    errorContainer = errorContainerDark,
    onError = onErrorDark,
    onErrorContainer = onErrorContainerDark,
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
            colorScheme = darkScheme,
            typography = baseline,
            content = {
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .background(MaterialTheme.colorScheme.background)
                ){
                    content()
                }
            }
        )
    }
}