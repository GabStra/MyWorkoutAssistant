package com.gabstra.myworkoutassistant.presentation.theme

import androidx.compose.ui.graphics.Color
import androidx.wear.compose.material.Colors

internal val wearColorPalette: Colors = Colors(
    primary = MyColors.Orange,
    primaryVariant =  Color(0xFFebebeb),
    secondary = Color(0xFF10EF6A),
    secondaryVariant = Color(0xFF3a6ea5),
    error = Color.Red,
    onPrimary = Color.White,
    onSecondary = Color.White,
    onError = Color.White
)

class MyColors {
    companion object {
        val Orange = Color(0xFFff6700)
        val Green = Color(0xFF10EF6A)
        val ComplementaryGreen = Color(0xFFEF1095)
    }
}
