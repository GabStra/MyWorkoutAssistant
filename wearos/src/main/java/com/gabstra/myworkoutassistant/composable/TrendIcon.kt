package com.gabstra.myworkoutassistant.composable

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.TrendingDown
import androidx.compose.material.icons.automirrored.filled.TrendingFlat
import androidx.compose.material.icons.automirrored.filled.TrendingUp
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.presentation.theme.MyColors
import kotlin.math.abs


@Composable
fun <T : Number> TrendIcon(currentValue: T, previousValue: T) {
    val percentageChange = abs((currentValue.toDouble() - previousValue.toDouble()) / previousValue.toDouble())

    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ){
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
            }
        }
        if(percentageChange != 0.0) {
            Text(
                text = "x${String.format("%.1f", percentageChange).replace(",", ".")}",
                style = MaterialTheme.typography.caption2,
            )
        }
    }

}