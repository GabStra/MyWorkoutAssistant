package com.gabstra.myworkoutassistant.composable

import android.annotation.SuppressLint
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.absoluteOffset
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape

import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
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
fun TrendComponentProgressBarWithMarker(
    modifier: Modifier = Modifier,
    label: String,
    ratio: Double,
    progressBarColor: Color,
    markers: List<MarkerData> = emptyList(),
    indicatorMarker: MarkerData? = null
) {

    Row(modifier = modifier, verticalAlignment = Alignment.CenterVertically) {
        Text(
            text = label,
            style = MaterialTheme.typography.title3.copy(fontSize = MaterialTheme.typography.title3.fontSize * 0.625f),
            textAlign = TextAlign.End
        )

        LinearProgressBarWithRounderBordersAndMarker(
            progress = ratio.toFloat(),
            modifier = Modifier.weight(1f).padding(bottom = 2.dp),
            progressBarColor = progressBarColor,
            markers = markers,
            indicatorMarker = indicatorMarker
        )

       /*
       if(ratio != 0.0 && ratio>1){
            val displayText = when {
                ratio >= 2 -> String.format("x%.1f", ratio).replace(',','.').replace(".0","")
                ratio >= 1.1 -> String.format("+%d%%", ((ratio - 1) * 100).roundToInt())
                else -> String.format("+%.1f%%", ((ratio - 1) * 100)).replace(',','.').replace(".0","")
            }
            Text(
                text = displayText,
                style = MaterialTheme.typography.title3.copy(fontSize = MaterialTheme.typography.title3.fontSize * 0.625f),
                color = MyColors.Green
            )
        }
        */
    }
}

@Composable
fun LinearProgressBarWithRounderBordersAndMarker(
    modifier: Modifier,
    progress: Float,
    progressBarColor: Color = Color(0xFFff6700),
    markers: List<MarkerData> = emptyList(),
    indicatorMarker: MarkerData? = null
) {
    val cornerRadius = 6.dp
    val roundedCornerShape: Shape = RoundedCornerShape(cornerRadius)
    val markerWidth = 30.dp

    BoxWithConstraints(
        modifier = modifier.height(34.dp),
    ) {

        val totalWidth = maxWidth
        val progressBarWidth = totalWidth - markerWidth

        // Calculate the effective width considering the rounded corners
        val effectiveWidth = progressBarWidth

        // Progress box
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(top=14.dp)
                .align(Alignment.Center)
        ) {
            SimpleProgressIndicator(
                progress = progress,
                trackColor = MaterialTheme.colors.background,
                progressBarColor = progressBarColor,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(6.dp)
                    .padding(horizontal = markerWidth/2)
                    .clip(roundedCornerShape)
            )
        }

        if(indicatorMarker!=null){
            val adjustedMarkerPercentage = indicatorMarker.ratio.coerceIn(0.0, 1.0)
            val markerOffset = effectiveWidth * adjustedMarkerPercentage.toFloat()

            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .align(Alignment.Center)
                    .background(Color.Transparent)
                    .absoluteOffset(
                        x = markerOffset,
                    ),
            ){
                Column(
                    modifier = Modifier
                        .height(10.dp)
                        .width(markerWidth)
                        .background(Color.Transparent),
                    //verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    ScalableText(
                        modifier = Modifier
                            .fillMaxSize()
                            .background(Color.Transparent),
                        text = indicatorMarker.text,
                        style = MaterialTheme.typography.title1,
                        color = indicatorMarker.textColor,
                        textAlign = TextAlign.Center,
                        minTextSize = 6.sp
                    )
                }
            }
        }

        markers.forEach { marker ->
            val adjustedMarkerPercentage = marker.ratio.coerceIn(0.0, 1.0)
            val markerOffset = effectiveWidth * adjustedMarkerPercentage.toFloat()

            // Marker box
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(top=14.dp)
                    .height(20.dp)
                    .align(Alignment.Center)
                    .background(Color.Transparent)
                    .absoluteOffset(
                        x = markerOffset,
                    ),
            ) {
                Column(
                    modifier = Modifier
                        .width(markerWidth)
                        .background(Color.Transparent),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ){
                    Canvas(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(6.dp)
                            .background(Color.Transparent)
                    ) {
                        val xPosition = size.width /2
                        drawLine(
                            color = marker.color,
                            start = Offset(xPosition, 0f),
                            end = Offset(xPosition, size.height),  // Leave space for text
                            strokeWidth = 2.dp.toPx(),
                        )
                    }
                    ScalableText(
                        modifier = Modifier
                            .fillMaxHeight(1f)
                            .fillMaxWidth()
                            .background(Color.Transparent),
                        text = marker.text,
                        style = MaterialTheme.typography.body2.copy(fontWeight = FontWeight.Medium),
                        color = marker.textColor,
                        textAlign = TextAlign.Center,
                        minTextSize = 6.sp
                    )
                }
            }
        }
    }
}

