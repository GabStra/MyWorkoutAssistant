package com.gabstra.myworkoutassistant.presentation.theme

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.wear.compose.material3.CheckboxButtonColors
import androidx.wear.compose.material3.ColorScheme
import androidx.wear.compose.material3.MaterialTheme
import com.gabstra.myworkoutassistant.shared.DarkGray
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.LighterGray
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
    onPrimaryContainer = LighterGray,

    secondary = Green,
    secondaryDim = Green,
    secondaryContainer = MediumDarkerGray,
    onSecondary = DarkGray,
    onSecondaryContainer = LighterGray,

    tertiary = Yellow,
    tertiaryDim = Yellow,
    tertiaryContainer = MediumDarkerGray,
    onTertiary = DarkGray,
    onTertiaryContainer = LighterGray,

    surfaceContainerLow = MediumDarkerGray,
    surfaceContainer = MediumDarkGray,
    surfaceContainerHigh = MediumLightGray,
    onSurface =  LighterGray, //Color(210, 210, 210),
    onSurfaceVariant = MediumLightGray,
    outline = MediumGray,
    outlineVariant = MediumLightGray,

    background = Color.Black,
    onBackground = LighterGray,

    error = Red,
    errorDim = Red,
    errorContainer = MediumDarkerGray,
    onError = LighterGray,
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
fun checkboxButtonColors(): CheckboxButtonColors {
    val colorScheme = MaterialTheme.colorScheme
    return CheckboxButtonColors(
        // Checked state colors
        checkedBoxColor = colorScheme.primary, // Orange - visible
        checkedCheckmarkColor = colorScheme.primaryContainer, // Light gray for visibility on orange background
        checkedContainerColor = colorScheme.primaryContainer, // MediumDarkerGray
        checkedContentColor = colorScheme.onPrimaryContainer, // LighterGray
        checkedIconColor = colorScheme.primary, // Orange
        checkedSecondaryContentColor = colorScheme.onPrimaryContainer, // LighterGray

        // Unchecked state colors
        uncheckedBoxColor = MediumLightGray, // Lighter than container for visibility
        uncheckedContainerColor = colorScheme.surfaceContainer, // MediumGray
        uncheckedContentColor = colorScheme.onSurface, // LighterGray
        uncheckedIconColor = colorScheme.primary, // Orange
        uncheckedSecondaryContentColor = colorScheme.onSurfaceVariant, // MediumLightGray

        // Disabled checked state colors
        disabledCheckedBoxColor = colorScheme.onSurface.copy(alpha = 0.12f),
        disabledCheckedCheckmarkColor = colorScheme.background.copy(alpha = 0.38f),
        disabledCheckedContainerColor = colorScheme.onSurface.copy(alpha = 0.12f),
        disabledCheckedContentColor = colorScheme.onSurface,
        disabledCheckedIconColor = colorScheme.onSurface,
        disabledCheckedSecondaryContentColor = colorScheme.onSurface,

        // Disabled unchecked state colors
        disabledUncheckedBoxColor = colorScheme.onSurface.copy(alpha = 0.12f),
        disabledUncheckedContainerColor = colorScheme.onSurface.copy(alpha = 0.12f),
        disabledUncheckedContentColor = colorScheme.onSurface,
        disabledUncheckedIconColor = colorScheme.onSurface,
        disabledUncheckedSecondaryContentColor = colorScheme.onSurface
    )
}

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