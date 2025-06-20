package com.gabstra.myworkoutassistant.presentation.theme

import androidx.compose.ui.graphics.Color
import androidx.wear.compose.material.Colors

internal val wearColorPalette: Colors = Colors(
    primary = MyColors.Orange,
    primaryVariant =  Color(0xFFebebeb),
    secondary = MyColors.Green,
    secondaryVariant = Color(0xFF3a6ea5),
    error = MyColors.Red,
    onPrimary = MyColors.White,
    onSecondary = MyColors.White,
    onError = MyColors.White,
    background = MyColors.MiddleGray,
)

class MyColors {
    companion object MyColors {
        val White = Color(0xFFF0F0F0)
        val Orange = Color(0xFFff6700)
        val Green = Color(0xFF119943)
        val Yellow = Color.hsl(50f, 0.85f, 0.65f)
        val Red = Color(0xFFed2020)

        val DarkGray = Color.DarkGray //Color(0xFF121212)
        val MiddleGray = Color(0xFF2E2E2E) // Lighter than DarkGray
        val LightGray = Color(0xFFB0B0B0) // Lighter than MiddleGray
    }
}
