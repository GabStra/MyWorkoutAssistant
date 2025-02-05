package com.gabstra.myworkoutassistant.composable

import android.util.Log
import android.widget.Toast
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.absoluteOffset
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.withTransform
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
import com.gabstra.myworkoutassistant.data.VibrateTwiceAndBeep
import com.gabstra.myworkoutassistant.presentation.theme.MyColors
import com.gabstra.myworkoutassistant.shared.colorsByZone
import com.gabstra.myworkoutassistant.shared.getMaxHearthRatePercentage
import com.gabstra.myworkoutassistant.shared.mapPercentage
import com.gabstra.myworkoutassistant.shared.mapPercentageToZone
import com.gabstra.myworkoutassistant.shared.zoneRanges
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import com.google.android.horologist.composables.ProgressIndicatorSegment
import com.google.android.horologist.composables.SegmentedProgressIndicator
import kotlinx.coroutines.FlowPreview
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
    hr: Int,
    age: Int,
    lowerBoundMaxHRPercent: Float?,
    upperBoundMaxHRPercent: Float?,
) {
    val context = LocalContext.current
    val mhrPercentage = remember(hr, age) { getMaxHearthRatePercentage(hr, age) }
    val scope = rememberCoroutineScope()
    var alertJob by remember { mutableStateOf<Job?>(null) }

    val alertCooldown = 1000L //5 seconds in milliseconds

    fun startAlertJob() {
        alertJob = scope.launch {
            delay(2000)
            Toast.makeText(context, "Heart rate over limit", Toast.LENGTH_LONG).show()
            while (isActive) {
                VibrateShortImpulse(context)
                delay(alertCooldown)
            }
        }
    }

    if(lowerBoundMaxHRPercent != null && upperBoundMaxHRPercent != null) {
        var isInTargetZoneForFiveSeconds by remember { mutableStateOf(false) }
        var zoneTrackingJob by remember { mutableStateOf<Job?>(null) }

        var alarmJob by remember { mutableStateOf<Job?>(null) }

        LaunchedEffect(mhrPercentage) {
            zoneTrackingJob?.cancel()

            if(mhrPercentage in lowerBoundMaxHRPercent..upperBoundMaxHRPercent) {
                if(isInTargetZoneForFiveSeconds) {
                    alarmJob?.cancel()
                    return@LaunchedEffect
                }

                zoneTrackingJob = scope.launch {
                    val startTime = System.currentTimeMillis()
                    while(isActive) {
                        val timeInZone = System.currentTimeMillis() - startTime
                        if(timeInZone >= 5000) { // 10 seconds
                            isInTargetZoneForFiveSeconds = true
                            break
                        }
                        delay(100) // Check every 100ms
                    }
                }
            } else if(isInTargetZoneForFiveSeconds) {
                alarmJob = scope.launch {
                    delay(5000)
                    Toast.makeText(context, "HR outside target zone", Toast.LENGTH_LONG).show()
                    while (isActive) {
                        VibrateTwiceAndBeep(context)
                        delay(2000)
                    }
                }
            }
        }

        DisposableEffect(Unit) {
            onDispose {
                zoneTrackingJob?.cancel()
            }
        }
    }

    LaunchedEffect(mhrPercentage) {
        if (mhrPercentage >= 100) {
            if(alertJob?.isActive == false){
                startAlertJob()
            }
        }else{
            alertJob?.cancel()
        }
    }

    DisposableEffect(Unit) {
        onDispose {
            alertJob?.cancel()
        }
    }

    HeartRateView(modifier, hr, mhrPercentage, colorsByZone, lowerBoundMaxHRPercent, upperBoundMaxHRPercent)
}


@Composable
private fun RotatingIndicator(rotationAngle: Float, fillColor: Color) {
    val density = LocalDensity.current.density
    val triangleSize = 6f

    BoxWithConstraints(
        modifier = Modifier.fillMaxSize()
    ) {
        val boxWidth = (constraints.maxWidth/density).dp
        val boxHeight = (constraints.maxHeight/density).dp

        val angleInRadians = Math.toRadians(rotationAngle.toDouble())

        val widthOffset = (constraints.maxWidth/2) - 22
        val heightOffset = (constraints.maxHeight/2) - 22

        val xRadius = ((widthOffset * cos(angleInRadians)) / density).dp
        val yRadius = ((heightOffset * sin(angleInRadians)) / density).dp

        Box(
            modifier = Modifier
                .fillMaxSize()
                .absoluteOffset(
                    x = (boxWidth / 2) - (triangleSize / density).dp + xRadius,
                    y = (boxHeight / 2) - (triangleSize / density).dp + yRadius,
                ),
        ) {
            Canvas(modifier = Modifier.size((triangleSize * 2 / density).dp)) {
                val trianglePath = Path().apply {
                    val height = (triangleSize * 2 / density).dp.toPx()
                    val width = height

                    // Create triangle pointing upward initially
                    moveTo(width / 2, 0f)          // Top point
                    lineTo(width, height * 0.866f) // Bottom right
                    lineTo(0f, height * 0.866f)    // Bottom left
                    close()
                }

                // Calculate rotation to point in direction of movement
                // Add 90 degrees (π/2) because our triangle points up by default
                // and we want it to point in the direction of travel
                val directionAngle = angleInRadians - Math.PI / 2 + Math.PI

                withTransform({
                    rotate(
                        degrees = Math.toDegrees(directionAngle).toFloat(),
                        pivot = center
                    )
                }) {
                    // Draw filled white triangle
                    drawPath(
                        path = trianglePath,
                        color = fillColor
                    )
                }
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
    mhrPercentage: Float,
    colorsByZone: Array<Color>,
    lowerBoundMaxHRPercent: Float?,
    upperBoundMaxHRPercent: Float?,
) {

    val segments = remember { getProgressIndicatorSegments() }

    val progress = remember(mhrPercentage) { mapPercentage(mhrPercentage) }
    val zone = remember(mhrPercentage) { mapPercentageToZone(mhrPercentage) }

    var displayMode by remember { mutableStateOf(0) }

    val textToDisplay = when(displayMode) {
        0 -> if (hr == 0) "-" else hr.toString()
        1 -> "Zone $zone"
        else -> "${(mhrPercentage).toInt()}%"
    }

    val showHeartIcon = displayMode == 0
    val context = LocalContext.current

    val startAngle = 115f
    val endAngle = 240f

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
                .clickable {
                    displayMode = (displayMode + 1) % 3
                    VibrateGentle(context)
                }
        ) {
            if(showHeartIcon){
                HeartIcon(
                    modifier = Modifier.size(15.dp),
                    tint = if (hr == 0) Color.DarkGray else colorsByZone[zone]
                )
                Spacer(modifier = Modifier.width(5.dp))
            }

            val textColor = when(displayMode) {
                0 ->  Color.White
                else -> colorsByZone[zone]
            }

            Text(
                text = textToDisplay,
                textAlign = TextAlign.Center,
                style = MaterialTheme.typography.caption1,
                color = if (hr == 0) Color.DarkGray else textColor
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

        Log.d("HeartRateCircularChart", "lowerBoundMaxHRPercent: $lowerBoundMaxHRPercent upperBoundMaxHRPercent: $upperBoundMaxHRPercent")

        if(lowerBoundMaxHRPercent != null && upperBoundMaxHRPercent != null){
            val lowerBoundRotationAngle = remember {
                val lowerBoundPercentage = mapPercentage(lowerBoundMaxHRPercent)
                getValueInRange(startAngle, endAngle, lowerBoundPercentage)
            }

            RotatingIndicator(lowerBoundRotationAngle, MyColors.Green)

            val upperBoundRotationAngle = remember {
                val upperBoundPercentage = mapPercentage(upperBoundMaxHRPercent)
                getValueInRange(startAngle, endAngle, upperBoundPercentage)
            }

            RotatingIndicator(upperBoundRotationAngle, MyColors.Red)
        }
    }
}


@OptIn(FlowPreview::class)
@Composable
fun HeartRateStandard(
    modifier: Modifier = Modifier,
    appViewModel: AppViewModel,
    hrViewModel: SensorDataViewModel,
    userAge : Int,
    lowerBoundMaxHRPercent: Float?,
    upperBoundMaxHRPercent: Float?,
) {
    val currentHeartRate by hrViewModel.heartRateBpm.collectAsState()
    val hr = currentHeartRate ?: 0

    LaunchedEffect(Unit) {
        while (true) {
            appViewModel.registerHeartBeat(hrViewModel.heartRateBpm.value ?: 0)
            delay(1000)
        }
    }

    HeartRateCircularChart(modifier = modifier, hr = hr, age = userAge, lowerBoundMaxHRPercent = lowerBoundMaxHRPercent, upperBoundMaxHRPercent = upperBoundMaxHRPercent)
}

@OptIn(FlowPreview::class)
@Composable
fun HeartRatePolar(
    modifier: Modifier = Modifier,
    appViewModel: AppViewModel,
    polarViewModel: PolarViewModel,
    userAge : Int,
    lowerBoundMaxHRPercent: Float?,
    upperBoundMaxHRPercent: Float?,
) {
    val hrData by polarViewModel.hrDataState.collectAsState()
    val hr = hrData ?: 0

    LaunchedEffect(Unit) {
        while (true) {
            appViewModel.registerHeartBeat(polarViewModel.hrDataState.value ?: 0)
            delay(1000)
        }
    }

    HeartRateCircularChart(modifier = modifier, hr = hr, age = userAge, lowerBoundMaxHRPercent = lowerBoundMaxHRPercent, upperBoundMaxHRPercent = upperBoundMaxHRPercent)
}