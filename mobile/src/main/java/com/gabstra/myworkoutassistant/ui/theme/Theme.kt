package com.gabstra.myworkoutassistant.ui.theme

import android.app.Activity
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat


val DarkGray = Color(30, 30, 30)
val MediumDarkGray = Color(60, 60, 60)
val MediumGray = Color(90, 90, 90)
val MediumLightGray = Color(120, 120, 120)
val LightGray = Color(240, 240, 240)

private val DarkColorScheme = darkColorScheme(
    primary = Color(0xFFff6700), // Orange
    background = Color(31,31,31)
)

private val LightColorScheme = lightColorScheme(
    primary = Color(0xFFff6700), // Orange
)

@Composable
fun MyWorkoutAssistantTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    dynamicColor: Boolean = true,
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
        colorScheme = if (darkTheme) DarkColorScheme else LightColorScheme,
        typography = Typography,
        content = content
    )
}