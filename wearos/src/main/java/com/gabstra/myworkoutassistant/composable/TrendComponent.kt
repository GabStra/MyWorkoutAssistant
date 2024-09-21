package com.gabstra.myworkoutassistant.composable

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize

import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.presentation.theme.MyColors


@Composable
fun <T : Number> TrendComponent(
    modifier: Modifier = Modifier,
    label: String,
    currentValue: T,
    previousValue: T
) {
    val percentageChange = (currentValue.toDouble() - previousValue.toDouble()) / previousValue.toDouble()

    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(5.dp),
        verticalAlignment = Alignment.CenterVertically
    ){
        Text(
            text = label,
            style = MaterialTheme.typography.caption2,
            textAlign = TextAlign.End
        )

        if(percentageChange != 0.0){
            val displayText = if (percentageChange <= 1) {
                val percentage = (percentageChange * 100).toInt()
                if (percentage > 0) "+${percentage}%" else "${percentage}%"
            } else {
                "x${String.format("%.2f", percentageChange).replace(",", ".")}"
            }
            Text(
                text = displayText,
                style = MaterialTheme.typography.caption2,
                color = if (percentageChange > 0) MyColors.Green else MyColors.ComplementaryGreen
            )
        }else{
            Text(
                text = "-",
                style = MaterialTheme.typography.caption2,
            )
        }
    }
}