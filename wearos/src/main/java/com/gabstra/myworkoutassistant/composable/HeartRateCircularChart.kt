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
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.PolarViewModel
import com.gabstra.myworkoutassistant.data.SensorDataViewModel
import com.gabstra.myworkoutassistant.data.VibrateGentle
import com.gabstra.myworkoutassistant.data.VibrateShortImpulse
import com.gabstra.myworkoutassistant.data.getContrastRatio
import com.gabstra.myworkoutassistant.presentation.theme.MyColors
import com.gabstra.myworkoutassistant.shared.colorsByZone
import com.gabstra.myworkoutassistant.shared.getMaxHearthRatePercentage
import com.gabstra.myworkoutassistant.shared.mapPercentage
import com.gabstra.myworkoutassistant.shared.mapPercentageToZone
import com.gabstra.myworkoutassistant.shared.zoneRanges
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import com.google.android.horologist.composables.ProgressIndicatorSegment
import com.google.android.horologist.composables.SegmentedProgressIndicator
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
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
    val scope = rememberCoroutineScope()
    var alertJob by remember { mutableStateOf<Job?>(null) }

    var isDataStale by remember { mutableStateOf(false) }

    LaunchedEffect(hr) {
        if (hr > 0) {
            isDataStale = false
            delay(5000)  // wait for 5 seconds
            isDataStale = true
        }
    }

    LaunchedEffect(hr) {
        while (isActive) {
            appViewModel.registerHeartBeat(hr)
            delay(500)
        }
    }

    var lastAlertTime by remember { mutableLongStateOf(0L) }
    val alertCooldown = 5000L //5 seconds in milliseconds

    fun startAlertJob() {
        alertJob = scope.launch {
            while (isActive) {
                val currentTime = System.currentTimeMillis()
                if (lastAlertTime == 0L || (currentTime - lastAlertTime >= alertCooldown)) {
                    Toast.makeText(context, "Heart rate over limit", Toast.LENGTH_LONG).show()
                    VibrateShortImpulse(context)
                    lastAlertTime = currentTime
                    delay(alertCooldown)
                } else {
                    delay(alertCooldown - (currentTime - lastAlertTime))
                }
            }
        }
    }

    LaunchedEffect(mhrPercentage) {
        alertJob?.cancel()
        if (mhrPercentage >= 100) {
            startAlertJob()
        }
    }

    HeartRateView(modifier, hr, isDataStale, mhrPercentage, colorsByZone)
}


@Composable
private fun RotatingCircle(rotationAngle: Float, fillColor: Color, number: Int) {
    val density = LocalDensity.current.density
    val circleRadius = 20f

    val textColor = if (getContrastRatio(fillColor, Color.Black) > getContrastRatio(fillColor, Color.White)) {
        Color.Black
    } else {
        Color.White
    }

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
            Canvas(modifier = Modifier.size((circleRadius * 2 / density).dp)) {
                drawCircle(
                    color = fillColor,
                    radius = (circleRadius / density).dp.toPx(),
                    center = center
                )
                drawCircle(
                    color = Color.Black,
                    radius = (circleRadius / density).dp.toPx(),
                    center = center,
                    style = Stroke(width = 3.dp.toPx())
                )
            }
            Box(modifier = Modifier
                .size((circleRadius * 2 / density).dp)
            ){
                ScalableText(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(3.dp),
                    text = number.toString(),
                    style = MaterialTheme.typography.body2.copy(fontWeight = FontWeight.Medium),
                    color = textColor,
                    textAlign = TextAlign.Center,
                )
            }
        }
    }
}

fun getValueInRange(startAngle: Float, endAngle: Float, percentage: Float): Float {
    return startAngle + (endAngle - startAngle) * percentage
}

@OptIn(ExperimentalHorologistApi::class, ExperimentalFoundationApi::class)
@Composable
private fun HeartRateView(
    modifier: Modifier,
    hr: Int,
    isDataStale: Boolean,
    mhrPercentage: Float,
    colorsByZone: Array<Color>
) {

    val segments = remember { getProgressIndicatorSegments() }

    val progress = remember(mhrPercentage) { mapPercentage(mhrPercentage) }
    val zone = remember(mhrPercentage) { mapPercentageToZone(mhrPercentage) }

    var isDisplayingHr by remember { mutableStateOf(true) }
    val textToDisplay = if(isDisplayingHr) if (hr == 0) "-" else hr.toString() else "Zone $zone"
    val context = LocalContext.current

    val startAngle = 115f
    val endAngle = 240f

    val targetRotationAngle = remember(progress) {
        getValueInRange(startAngle, endAngle, progress)
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
                HeartIcon(
                    modifier = Modifier.size(15.dp),
                    tint =  if (hr == 0) Color.DarkGray else MyColors.Red
                )
                Spacer(modifier = Modifier.width(5.dp))
            }
            Text(
                text = textToDisplay,
                textAlign = TextAlign.Center,
                style = MaterialTheme.typography.caption1,
                color = if (hr == 0) Color.DarkGray else Color.White
            )
        }

        SegmentedProgressIndicator(
            trackSegments = segments,
            progress = progress,
            modifier = Modifier.fillMaxSize(),
            strokeWidth = 4.dp,
            paddingAngle = 2f,
            startAngle = startAngle,
            endAngle = endAngle,
            trackColor = Color.DarkGray,
        )

        if(hr != 0) {
            RotatingCircle(targetRotationAngle, colorsByZone[zone],zone)
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