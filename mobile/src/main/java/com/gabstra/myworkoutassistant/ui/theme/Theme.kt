package com.gabstra.myworkoutassistant.ui.theme


import android.app.Activity
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat
import com.gabstra.myworkoutassistant.shared.DarkGray
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.LighterGray
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.MediumDarkerGray
import com.gabstra.myworkoutassistant.shared.MediumGray
import com.gabstra.myworkoutassistant.shared.MediumLightGray
import com.gabstra.myworkoutassistant.shared.Orange
import com.gabstra.myworkoutassistant.shared.Red
import com.gabstra.myworkoutassistant.shared.SoftGray
import com.gabstra.myworkoutassistant.shared.Yellow

private val DarkColorScheme = darkColorScheme(
    primary = Orange,
    onPrimary = LighterGray,
    primaryContainer = MediumDarkerGray,
    onPrimaryContainer = LighterGray,
    inversePrimary = Orange,

    secondary = Green,
    onSecondary = Color.White,
    secondaryContainer = MediumDarkerGray,
    onSecondaryContainer = LighterGray,

    tertiary = Yellow,
    onTertiary = DarkGray,
    tertiaryContainer = MediumDarkerGray,
    onTertiaryContainer = LighterGray,

    background = Color.Black,
    onBackground = LighterGray,
    surface = MediumDarkerGray,
    onSurface = LighterGray,
    surfaceVariant = MediumDarkGray,
    onSurfaceVariant = SoftGray,
    surfaceTint = Orange,
    inverseSurface = LighterGray,
    inverseOnSurface = DarkGray,

    error = Red,
    onError = Color.White,
    errorContainer = MediumDarkerGray,
    onErrorContainer = Color.White,

    outline = MediumGray,
    outlineVariant = MediumLightGray,
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
