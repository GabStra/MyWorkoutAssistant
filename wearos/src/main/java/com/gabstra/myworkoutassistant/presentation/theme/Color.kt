package com.gabstra.myworkoutassistant.presentation.theme

import androidx.compose.ui.graphics.Color
import androidx.wear.compose.material.Colors

internal val wearColorPalette: Colors = Colors(
    primary = MyColors.Orange,
    primaryVariant =  Color(0xFFebebeb),
    secondary = MyColors.Green,
    secondaryVariant = Color(0xFF3a6ea5),
    error = Color.hsl(9f, 0.88f, 0.45f),
    onPrimary = MyColors.White,
    onSecondary = MyColors.White,
    onError = MyColors.White,
    background = Color.DarkGray,

)

class MyColors {
    companion object {
        val White = Color(0xFFF0F0F0)
        val Orange = Color(0xFFff6700)
        val Green = Color(0xFF119943)
        val Yellow = Color.hsl(50f, 0.85f, 0.65f)
        val Red = Color(0xFFed2020)
        val LightGray = Color(0xFFAAAAAA)
        val DarkGray = Color(0x80F0F0F0)
    }
}
