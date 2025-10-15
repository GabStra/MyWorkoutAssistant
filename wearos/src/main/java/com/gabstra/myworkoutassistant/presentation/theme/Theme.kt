package com.gabstra.myworkoutassistant.presentation.theme

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.wear.compose.material3.ColorScheme
import androidx.wear.compose.material3.MaterialTheme
import com.gabstra.myworkoutassistant.shared.DarkGray
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.LightGray
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.MediumDarkerGray
import com.gabstra.myworkoutassistant.shared.MediumGray
import com.gabstra.myworkoutassistant.shared.MediumLightGray
import com.gabstra.myworkoutassistant.shared.Orange
import com.gabstra.myworkoutassistant.shared.Red
import com.gabstra.myworkoutassistant.shared.Yellow

val darkScheme = ColorScheme(
    primary = Orange,
    primaryDim = Orange,
    primaryContainer = MediumDarkerGray,
    onPrimary = DarkGray,
    onPrimaryContainer = LightGray,

    secondary = Green,
    secondaryDim = Green,
    secondaryContainer = MediumDarkerGray,
    onSecondary = DarkGray,
    onSecondaryContainer = LightGray,

    tertiary = Yellow,
    tertiaryDim = Yellow,
    tertiaryContainer = MediumDarkerGray,
    onTertiary = DarkGray,
    onTertiaryContainer = LightGray,

    surfaceContainerLow = MediumDarkerGray,
    surfaceContainer = MediumDarkGray,
    surfaceContainerHigh = MediumGray,
    onSurface = LightGray,
    onSurfaceVariant = MediumLightGray,
    outline = MediumGray,
    outlineVariant = MediumLightGray,

    background = Color.Black,
    onBackground = LightGray,

    error = Red,
    errorDim = Red,
    errorContainer = MediumDarkerGray,
    onError = LightGray,
    onErrorContainer = Red,
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