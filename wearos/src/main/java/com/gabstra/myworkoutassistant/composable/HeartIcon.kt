package com.gabstra.myworkoutassistant.composable

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.wear.compose.material.Icon

@Composable
fun HeartIcon(
    modifier: Modifier
){
    Icon(
        imageVector = Icons.Filled.Favorite,
        contentDescription = "Heart",
        tint = Color.hsl(9f,0.88f,0.45f),
        modifier = modifier
    )
}