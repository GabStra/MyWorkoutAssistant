package com.gabstra.myworkoutassistant.composables

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.wear.compose.material3.Icon
import com.gabstra.myworkoutassistant.R

@Composable
fun HeartIcon(
    modifier: Modifier,
    tint: Color
){
    Icon(
        imageVector = Icons.Filled.Favorite,
        contentDescription = stringResource(R.string.chart_cd_heart),
        tint = tint,
        modifier = modifier
    )
}