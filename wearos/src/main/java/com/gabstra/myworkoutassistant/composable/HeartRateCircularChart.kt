package com.gabstra.myworkoutassistant.composable

import android.widget.Toast
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.absoluteOffset
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Fill
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.PolarViewModel
import com.gabstra.myworkoutassistant.data.SensorDataViewModel
import com.gabstra.myworkoutassistant.data.VibrateGentle
import com.gabstra.myworkoutassistant.data.VibrateShortImpulse
import com.gabstra.myworkoutassistant.shared.colorsByZone
import com.gabstra.myworkoutassistant.shared.getMaxHearthRatePercentage
import com.gabstra.myworkoutassistant.shared.mapPercentage
import com.gabstra.myworkoutassistant.shared.mapPercentageToZone
import com.gabstra.myworkoutassistant.shared.zoneRanges
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import com.google.android.horologist.composables.ProgressIndicatorSegment
import com.google.android.horologist.composables.SegmentedProgressIndicator
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlin.math.cos
import kotlin.math.sin

private fun getProgressIndicatorSegments() = listOf(
    ProgressIndicatorSegment(.166f, colorsByZone[0]),
    ProgressIndicatorSegment(.166f, colorsByZone[1]),
    ProgressIndicatorSegment(.166f, colorsByZone[2]),
    ProgressIndicatorSegment(.166f, colorsByZone[3]),
    ProgressIndicatorSegment(.166f, colorsByZone[4]),
    ProgressIndicatorSegment(.166f, colorsByZone[5]),
)

@Composable
fun HeartRateCircularChart(
    modifier: Modifier = Modifier,
    appViewModel: AppViewModel,
    hr: Int,
    age: Int = 28
) {
    val context = LocalContext.current
    val mhrPercentage = remember(hr, age) { getMaxHearthRatePercentage(hr, age) }

    var isDataStale by remember { mutableStateOf(false) }

    // Simplified data stale counter using LaunchedEffect for automatic cancellation
    LaunchedEffect(hr) {
        if (hr > 0) {
            isDataStale = false
            delay(5000)  // wait for 5 seconds
            isDataStale = true
        }
    }

    // Collect the heart rate value from the StateFlow and call registerHeartBeat at 500 ms intervals
    // Simplified version without explicitly using a ticker channel
    LaunchedEffect(hr) {
        while (isActive) {
            appViewModel.registerHeartBeat(hr)
            delay(500)
        }
    }

    // Handle heart rate over limit scenario
    if (mhrPercentage > 100) {
        SideEffect {
            Toast.makeText(context, "Heart rate over limit", Toast.LENGTH_SHORT).show()
            VibrateShortImpulse(context)
        }
    }

    HeartRateView(modifier, hr, isDataStale, mhrPercentage, colorsByZone)
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun RowScope.combinedClickable(
    onClick: () -> Unit,
    onLongClick: () -> Unit
): Modifier = Modifier.combinedClickable(
    onClick = onClick,
    onLongClick = onLongClick
)


@Composable
private fun RotatingCircle(rotationAngle: Float, fillColor: Color) {
    val density = LocalDensity.current.density
    val circleRadius = 20f

    BoxWithConstraints(
        modifier = Modifier.fillMaxSize()
    ) {
        val boxWidth = (constraints.maxWidth/density).dp
        val boxHeight = (constraints.maxHeight/density).dp


        val angleInRadians = Math.toRadians(rotationAngle.toDouble())

        val widthOffset = (constraints.maxWidth/2) - 5
        val heightOffset = (constraints.maxHeight/2) - 5

        val xRadius = ((widthOffset * cos(angleInRadians)) / density).dp
        val yRadius = ((heightOffset * sin(angleInRadians)) / density).dp

        Box(
            modifier = Modifier
                .fillMaxSize()
                .absoluteOffset(
                    x = (boxWidth/2) - (circleRadius / density).dp + xRadius,
                    y = (boxHeight/2) - (circleRadius / density).dp + yRadius,
                ),
        ) {
            Box(modifier = Modifier
                .size((circleRadius * 2 / density).dp)
                .background(fillColor, CircleShape)
                .border(3.dp, Color.Black, CircleShape)
            )
        }
    }
}

private fun mapProgressToAngle(progress: Float, colorCount: Int): Float {
    val baseAngle = 110f
    val totalAngleRange = 120f
    val gapAngle = 2f
    val totalGapAngle = gapAngle * (colorCount - 1)
    val effectiveAngleRange = totalAngleRange - totalGapAngle
    val segmentAngleSize = effectiveAngleRange / colorCount

    val segmentIndex = (progress * colorCount).toInt().coerceIn(0, colorCount - 1)
    val segmentProgress = (progress * colorCount) % 1f

    return baseAngle +
            (segmentIndex * (segmentAngleSize + gapAngle)) +
            (segmentProgress * segmentAngleSize)
}

@OptIn(ExperimentalHorologistApi::class, ExperimentalFoundationApi::class)
@Composable
private fun HeartRateView(
    modifier: Modifier,
    hr: Int,
    isDataStale: Boolean,
    mhrPercentage: Float,
    colors: Array<Color>
) {
    val progress = remember(mhrPercentage) { mapPercentage(mhrPercentage) }
    val zone = remember(mhrPercentage) { mapPercentageToZone(mhrPercentage) }

    var isDisplayingHr by remember { mutableStateOf(true) }
    val textToDisplay = if(isDisplayingHr) if (hr == 0) "-" else hr.toString() else "Zone $zone"
    val context = LocalContext.current

    val targetRotationAngle = remember(progress, colors.size) {
        mapProgressToAngle(progress, colors.size)
    }

    Box(
        modifier = modifier,
        contentAlignment = Alignment.BottomCenter
    ) {
        Row(
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .width(60.dp)
                .height(20.dp)
                .padding(top = 5.dp)
                .combinedClickable(
                    onClick = { },
                    onLongClick = {
                        isDisplayingHr = !isDisplayingHr
                        VibrateGentle(context)
                    }
                )
        ) {
            if(isDisplayingHr){
                HeartIcon(modifier = Modifier.size(15.dp))
                Spacer(modifier = Modifier.width(5.dp))
            }
            Text(
                text = textToDisplay,
                textAlign = TextAlign.Center,
                style = MaterialTheme.typography.caption1,
                color = if (isDataStale) Color.Gray else Color.White
            )
        }

        var accumulatedAngle = 110f
        val baseGapAngle = 2f
        val size = 120f / colors.size

        colors.forEach { color ->
            SegmentedProgressIndicator(
                trackSegments = listOf(ProgressIndicatorSegment(1f,color)),
                progress = 1f,
                modifier = Modifier.fillMaxSize().alpha(1f),
                strokeWidth = 4.dp,
                paddingAngle = 2f,
                startAngle = accumulatedAngle,
                endAngle = accumulatedAngle + size,
                trackColor = Color.White,
            )

            accumulatedAngle += size + baseGapAngle
        }

        if(hr != 0) {
            val rangeIndex = zoneRanges.indexOfFirst { mhrPercentage >= it.first && mhrPercentage <= it.second }
            RotatingCircle(targetRotationAngle, colors[rangeIndex])
        }
    }
}


@Composable
fun HeartRateStandard(
    modifier: Modifier = Modifier,
    appViewModel: AppViewModel,
    hrViewModel: SensorDataViewModel,
    userAge : Int
) {
    val currentHeartRate by hrViewModel.heartRateBpm.collectAsState()
    val hr = currentHeartRate ?: 0
    HeartRateCircularChart(modifier = modifier,appViewModel, hr = hr, age = userAge)
}

@Composable
fun HeartRatePolar(
    modifier: Modifier = Modifier,
    appViewModel: AppViewModel,
    polarViewModel: PolarViewModel,
    userAge : Int
) {
    val hrData by polarViewModel.hrDataState.collectAsState()
    val hr = hrData ?: 0
    HeartRateCircularChart(modifier = modifier,appViewModel, hr = hr, age = userAge)
}