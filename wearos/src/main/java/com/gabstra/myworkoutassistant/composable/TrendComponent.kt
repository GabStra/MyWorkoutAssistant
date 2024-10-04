package com.gabstra.myworkoutassistant.composable

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.LinearProgressIndicator

import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
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
    val percentageChange = if (previousValue.toDouble() != 0.0) {
        (currentValue.toDouble() - previousValue.toDouble()) / previousValue.toDouble()
    } else {
        0.0
    }

    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(5.dp),
        verticalAlignment = Alignment.CenterVertically
    ){
        Text(
            text = label,
            style = MaterialTheme.typography.caption3,
            textAlign = TextAlign.End
        )

        if(percentageChange != 0.0){
            val percentage = (percentageChange * 100).toInt()
            val displayText = if (percentage > 0) "+${percentage}%" else "${percentage}%"
            Text(
                text = displayText,
                style = MaterialTheme.typography.caption3,
                color = if (percentageChange > 0) MyColors.Green else MyColors.ComplementaryGreen
            )
        }else{
            Text(
                text = "-",
                style = MaterialTheme.typography.caption3,
            )
        }
    }
}

@Composable
fun <T : Number> TrendComponent(
    modifier: Modifier = Modifier,
    label: String,
    percentage: Double
) {

    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(5.dp),
        verticalAlignment = Alignment.CenterVertically
    ){
        Text(
            text = label,
            style = MaterialTheme.typography.caption3,
            textAlign = TextAlign.End
        )

        if(percentage != 0.0){
            val displayText = "${percentage.toInt()}%"
            Text(
                text = displayText,
                style = MaterialTheme.typography.caption3,
                color = if (percentage >= 1) MyColors.Green else MyColors.ComplementaryGreen
            )
        }else{
            Text(
                text = "-",
                style = MaterialTheme.typography.caption3,
            )
        }
    }
}

@Composable
fun TrendComponentProgressBar(
    modifier: Modifier = Modifier,
    label: String,
    percentage: Double
) {

    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(5.dp),
        verticalAlignment = Alignment.CenterVertically
    ){
        Text(
            text = label,
            style = MaterialTheme.typography.caption3,
            textAlign = TextAlign.End
        )

        LinearProgressBarWithRounderBorders(
            progress = percentage.toFloat(),
            modifier = Modifier
                .weight(1f)
        )

        if(percentage != 0.0 && percentage>1){
            val displayText = "+${((percentage.toInt()*100)-100)}%"
            Text(
                text = displayText,
                style = MaterialTheme.typography.caption3,
                color = MyColors.Green
            )
        }
    }
}

@Composable
fun LinearProgressBarWithRounderBorders(progress: Float, modifier: Modifier = Modifier){
    val roundedCornerShape: Shape = RoundedCornerShape(6.dp)

    Box(
        modifier = modifier
            .clip(roundedCornerShape)
            .fillMaxWidth()
    ) {
        LinearProgressIndicator(
            progress = { progress },
            trackColor = Color.DarkGray,
            color = if(progress>=1) MyColors.Green else Color(0xFFff6700),
            modifier = Modifier
                .fillMaxWidth()
                .height(6.dp)
                .clip(roundedCornerShape)
        )
    }
}