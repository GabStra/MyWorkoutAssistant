package com.gabstra.myworkoutassistant.composable

import android.annotation.SuppressLint
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check

import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.round
import com.gabstra.myworkoutassistant.presentation.theme.MyColors
import com.kevinnzou.compose.progressindicator.SimpleProgressIndicator
import kotlin.math.roundToInt


@SuppressLint("DefaultLocale")
@Composable
fun <T : Number> TrendComponent(
    modifier: Modifier = Modifier,
    label: String,
    currentValue: T,
    previousValue: T
) {
    val ratio = if (previousValue.toDouble() != 0.0) {
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
            style = MaterialTheme.typography.title3.copy(fontSize = MaterialTheme.typography.title3.fontSize * 0.625f),
            textAlign = TextAlign.End
        )

        if(ratio != 0.0){
            val displayText = when {
                ratio >= 1 -> String.format("x%.2f", ratio+1).replace(',','.').replace(".00","")
                ratio >= 0.1 -> String.format("+%d%%", (ratio * 100).roundToInt())
                ratio > 0 -> String.format("+%.1f%%", (ratio * 100)).replace(',','.').replace(".0","")
                ratio <= -0.1 -> String.format("%d%%", (ratio * 100).roundToInt())
                else -> String.format("%.1f%%", (ratio * 100)).replace(',','.').replace(".0","")
            }

            Text(
                text = displayText,
                style = MaterialTheme.typography.title3.copy(fontSize = MaterialTheme.typography.title3.fontSize * 0.625f),
                color = if (ratio > 0) MyColors.Green else MyColors.Red
            )
        }else{
            Text(
                text = "-",
                style = MaterialTheme.typography.title3.copy(fontSize = MaterialTheme.typography.title3.fontSize * 0.625f),
            )
        }
    }
}

@SuppressLint("DefaultLocale")
@Composable
fun TrendComponentProgressBar(
    modifier: Modifier = Modifier,
    label: String,
    ratio: Double,
    progressBarColor: Color? = null
) {

    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(5.dp),
    ){
        Text(
            text = label,
            style = MaterialTheme.typography.caption3,
            textAlign = TextAlign.End
        )

        LinearProgressBarWithRounderBorders(
            progress = ratio.toFloat(),
            modifier = Modifier
                .weight(1f),
            progressBarColor = progressBarColor ?: if(ratio>=1) MyColors.Green else Color(0xFFff6700),
        )

        if(ratio != 0.0 && ratio>1){
            val displayText = when {
                ratio >= 2 -> String.format("x%.2f", ratio).replace(',','.').replace(".00","")
                ratio >= 1.1 -> String.format("+%d%%", ((ratio - 1) * 100).roundToInt())
                else -> String.format("+%.1f%%", ((ratio - 1) * 100)).replace(',','.').replace(".0","")
            }
            Text(
                text = displayText,
                style = MaterialTheme.typography.caption3,
                color = MyColors.Green
            )
        }
    }
}

@Composable
fun LinearProgressBarWithRounderBorders(
    progress: Float,
    modifier: Modifier = Modifier,
    progressBarColor: Color = Color(0xFFff6700)
){
    val roundedCornerShape: Shape = RoundedCornerShape(6.dp)

    Box(
        modifier = modifier
            .clip(roundedCornerShape)
            .fillMaxWidth()
    ) {
        SimpleProgressIndicator(
            progress = progress,
            trackColor = MaterialTheme.colors.background,
            progressBarColor = progressBarColor,
            modifier = Modifier
                .fillMaxWidth()
                .height(6.dp)
                .clip(roundedCornerShape)
        )
    }
}


data class MarkerData(
    val ratio: Double,
    val text: String,
    val color:Color = MyColors.Orange,
    val textColor:Color = Color.White
)


@SuppressLint("DefaultLocale")
@Composable
fun ProgressIndicator(
    modifier: Modifier,
    ratio: Double,
    progressBarColor: Color,
) {
    val cornerRadius = 3.dp
    val roundedCornerShape: Shape = RoundedCornerShape(cornerRadius)

    Row(modifier = modifier, horizontalArrangement = Arrangement.Center){
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(5.dp)
        ){
            Row(modifier = Modifier.height(6.dp).weight(1f).clip(roundedCornerShape)){
                SimpleProgressIndicator(
                    progress = ratio.toFloat(),
                    trackColor = Color.DarkGray,
                    progressBarColor = progressBarColor,
                    modifier = Modifier.fillMaxHeight().weight(1f),
                )
            }
            /*Icon(
                imageVector = Icons.Filled.Check,
                modifier = Modifier.size(20.dp),
                contentDescription = "Streak",
                tint = if(ratio>=1) MyColors.Green else Color.DarkGray,
            )*/
        }
    }

}

