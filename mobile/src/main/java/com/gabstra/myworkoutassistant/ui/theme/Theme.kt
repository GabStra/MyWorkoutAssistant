package com.gabstra.myworkoutassistant.ui.theme


import android.app.Activity
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat
import com.gabstra.myworkoutassistant.shared.DarkGray
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.LightGray
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.MediumDarkerGray
import com.gabstra.myworkoutassistant.shared.MediumGray
import com.gabstra.myworkoutassistant.shared.Orange
import com.gabstra.myworkoutassistant.shared.Red
import com.gabstra.myworkoutassistant.shared.Yellow

private val DarkColorScheme = darkColorScheme(
    primary = Orange,
    onPrimary = DarkGray,
    primaryContainer = MediumDarkGray,
    onPrimaryContainer = LightGray,
    inversePrimary = Orange,

    secondary = Green,
    onSecondary = LightGray,
    secondaryContainer = MediumDarkerGray,
    onSecondaryContainer = LightGray,

    tertiary = Yellow,
    onTertiary = DarkGray,
    tertiaryContainer = MediumDarkerGray,
    onTertiaryContainer = LightGray,

    background = DarkGray,
    onBackground = LightGray,
    surface = MediumDarkerGray,
    onSurface = LightGray,
    surfaceVariant = MediumDarkGray,
    onSurfaceVariant = LightGray,
    surfaceTint = Orange,
    inverseSurface = LightGray,
    inverseOnSurface = DarkGray,

    error = Red,
    onError = LightGray,
    errorContainer = MediumDarkerGray,
    onErrorContainer = LightGray,

    outline = MediumGray,
    outlineVariant = MediumDarkGray,
    scrim = DarkGray
)

@Composable
fun MyWorkoutAssistantTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit
) {
    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            val window = (view.context as Activity).window
            WindowCompat.setDecorFitsSystemWindows(window, true)
        }
    }

    MaterialTheme(
        colorScheme = DarkColorScheme,
        typography = Typography,
        content = content
    )
}