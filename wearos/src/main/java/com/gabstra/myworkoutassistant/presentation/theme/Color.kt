package com.gabstra.myworkoutassistant.presentation.theme

import androidx.compose.ui.graphics.Color
import androidx.wear.compose.material.Colors

internal val wearColorPalette: Colors = Colors(
    primary = MyColors.Orange,
    primaryVariant =  Color(0xFFebebeb),
    secondary = MyColors.Green,
    secondaryVariant = Color(0xFF3a6ea5),
    error = Color.hsl(9f, 0.88f, 0.45f),
    onPrimary = Color.White,
    onSecondary = Color.White,
    onError = Color.White,
    background = Color.DarkGray,
)

class MyColors {
    companion object {
        val Orange = Color(0xFFff6700)
        val Green = Color.hsl(113f, 0.79f, 0.34f)
        val Red = Color.hsl(9f, 0.88f, 0.45f)
    }
}
