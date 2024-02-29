package com.gabstra.myworkoutassistant.composable

import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.TrendingDown
import androidx.compose.material.icons.automirrored.filled.TrendingFlat
import androidx.compose.material.icons.automirrored.filled.TrendingUp
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.Icon
import com.gabstra.myworkoutassistant.presentation.theme.MyColors


@Composable
fun <T : Number> TrendIcon(currentValue: T, previousValue: T) {
    when {
        currentValue.toDouble() > previousValue.toDouble() -> {
            Icon(
                imageVector = Icons.AutoMirrored.Filled.TrendingUp,
                contentDescription = "Up",
                modifier = Modifier.size(30.dp),
                tint = MyColors.Green
            )
        }

        currentValue.toDouble() < previousValue.toDouble() -> {
            Icon(
                imageVector = Icons.AutoMirrored.Filled.TrendingDown,
                contentDescription = "Down",
                modifier = Modifier.size(30.dp),
                tint = MyColors.ComplementaryGreen
            )
        }

         else -> {
             Icon(
                 imageVector = Icons.AutoMirrored.Filled.TrendingFlat,
                 contentDescription = "Same",
                 modifier = Modifier.size(30.dp).alpha(0f)
             )
         }
    }
}