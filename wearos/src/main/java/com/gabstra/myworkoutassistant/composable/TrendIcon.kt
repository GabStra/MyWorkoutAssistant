package com.gabstra.myworkoutassistant.composable

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column

import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.TrendingDown
import androidx.compose.material.icons.automirrored.filled.TrendingFlat
import androidx.compose.material.icons.automirrored.filled.TrendingUp
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.presentation.theme.MyColors
import kotlin.math.abs


@Composable
fun <T : Number> TrendIcon(currentValue: T, previousValue: T) {
    val percentageChange = (currentValue.toDouble() - previousValue.toDouble()) / previousValue.toDouble()

    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ){
        when {
            currentValue.toDouble() > previousValue.toDouble() -> {
                Icon(
                    imageVector = Icons.AutoMirrored.Filled.TrendingUp,
                    contentDescription = "Up",
                    modifier = Modifier.size(35.dp),
                    tint = MyColors.Green
                )
            }

            currentValue.toDouble() < previousValue.toDouble() -> {
                Icon(
                    imageVector = Icons.AutoMirrored.Filled.TrendingDown,
                    contentDescription = "Down",
                    modifier = Modifier.size(35.dp),
                    tint = MyColors.ComplementaryGreen
                )
            }
            else -> {
                Icon(
                    imageVector = Icons.AutoMirrored.Filled.TrendingFlat,
                    contentDescription = "Flat",
                    modifier = Modifier.size(35.dp).alpha(0f),
                )
            }
        }

        if(percentageChange != 0.0){
            val displayText = if (percentageChange <= 1) {
                val percentage = (percentageChange * 100).toInt()
                if (percentage > 0) "+${percentage}%" else "${percentage}%"
            } else {
                "x${String.format("%.2f", percentageChange).replace(",", ".")}"
            }

            Text(
                modifier = Modifier.width(40.dp),
                text = displayText,
                style = MaterialTheme.typography.caption2,
                textAlign = TextAlign.Center,
                color = if (percentageChange > 0) MyColors.Green else MyColors.ComplementaryGreen
            )
        }
    }
}