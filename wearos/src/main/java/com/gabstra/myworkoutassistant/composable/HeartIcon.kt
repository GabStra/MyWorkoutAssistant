package com.gabstra.myworkoutassistant.composable

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.wear.compose.material.Icon
import com.gabstra.myworkoutassistant.presentation.theme.MyColors

@Composable
fun HeartIcon(
    modifier: Modifier,
    tint: Color
){
    Icon(
        imageVector = Icons.Filled.Favorite,
        contentDescription = "Heart",
        tint = tint,
        modifier = modifier
    )
}