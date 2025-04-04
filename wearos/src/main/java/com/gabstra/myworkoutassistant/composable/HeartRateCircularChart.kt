package com.gabstra.myworkoutassistant.composable

import android.widget.Toast
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.ArrowForward
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.QuestionMark
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.PolarViewModel
import com.gabstra.myworkoutassistant.data.SensorDataViewModel
import com.gabstra.myworkoutassistant.data.VibrateGentle
import com.gabstra.myworkoutassistant.data.VibrateShortImpulse
import com.gabstra.myworkoutassistant.data.VibrateTwiceAndBeep
import com.gabstra.myworkoutassistant.data.getValueInRange
import com.gabstra.myworkoutassistant.presentation.theme.MyColors
import com.gabstra.myworkoutassistant.shared.colorsByZone
import com.gabstra.myworkoutassistant.shared.getMaxHearthRatePercentage
import com.gabstra.myworkoutassistant.shared.mapPercentage
import com.gabstra.myworkoutassistant.shared.mapPercentageToZone
import com.gabstra.myworkoutassistant.shared.viewmodels.HeartRateChangeViewModel
import com.gabstra.myworkoutassistant.shared.viewmodels.HeartRateChangeViewModel.TrendDirection
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import com.google.android.horologist.composables.ProgressIndicatorSegment
import com.google.android.horologist.composables.SegmentedProgressIndicator
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlin.math.roundToInt

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
    heartRateChangeViewModel: HeartRateChangeViewModel,
    hr: Int,
    age: Int,
    lowerBoundMaxHRPercent: Float?,
    upperBoundMaxHRPercent: Float?,
) {
    val context = LocalContext.current
    val mhrPercentage = remember(hr, age) { getMaxHearthRatePercentage(hr, age) }
    val scope = rememberCoroutineScope()
    var alertJob by remember { mutableStateOf<Job?>(null) }
    var zoneTrackingJob by remember { mutableStateOf<Job?>(null) }
    var alarmJob by remember { mutableStateOf<Job?>(null) }

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
        var reachedTargetOnce by remember { mutableStateOf(false) }


        LaunchedEffect(mhrPercentage) {
            if(alertJob?.isActive == true) return@LaunchedEffect

            if(mhrPercentage in lowerBoundMaxHRPercent..upperBoundMaxHRPercent) {
                if(alarmJob?.isActive == true) {
                    alarmJob?.cancel()
                }

                if(zoneTrackingJob?.isActive == true) {
                    return@LaunchedEffect
                }

                zoneTrackingJob = scope.launch {
                    delay(5000)
                    reachedTargetOnce = true
                }
            } else{
                zoneTrackingJob?.cancel()

                if(!reachedTargetOnce || alarmJob?.isActive == true) {
                    return@LaunchedEffect
                }

                alarmJob = scope.launch {
                    delay(5000)
                    appViewModel.lightScreenUp()
                    Toast.makeText(context, "HR outside target zone", Toast.LENGTH_LONG).show()
                    while (isActive) {
                        VibrateTwiceAndBeep(context)
                        delay(2500)
                    }
                }
            }
        }
    }

    LaunchedEffect(mhrPercentage) {
        if (mhrPercentage >= 100) {
            if(alertJob?.isActive == false){
                startAlertJob()
                zoneTrackingJob?.cancel()
                alarmJob?.cancel()
            }
        }else{
            alertJob?.cancel()
        }
    }

    DisposableEffect(Unit) {
        onDispose {
            alertJob?.cancel()
            zoneTrackingJob?.cancel()
            alarmJob?.cancel()
        }
    }

    HeartRateView(modifier,appViewModel,heartRateChangeViewModel, hr, mhrPercentage, colorsByZone, lowerBoundMaxHRPercent, upperBoundMaxHRPercent)
}

@OptIn(ExperimentalHorologistApi::class, ExperimentalFoundationApi::class)
@Composable
private fun HeartRateView(
    modifier: Modifier,
    appViewModel: AppViewModel,
    heartRateChangeViewModel: HeartRateChangeViewModel,
    hr: Int,
    mhrPercentage: Float,
    colorsByZone: Array<Color>,
    lowerBoundMaxHRPercent: Float?,
    upperBoundMaxHRPercent: Float?,
) {
    val formattedChangeRate by heartRateChangeViewModel.formattedChangeRate.collectAsState()
    val confidenceLevel by heartRateChangeViewModel.confidenceLevel.collectAsState()
    val hrTrend by heartRateChangeViewModel.heartRateTrend.collectAsState()

    val segments = remember { getProgressIndicatorSegments() }

    val progress = remember(mhrPercentage) { mapPercentage(mhrPercentage) }
    val zone = remember(mhrPercentage) { mapPercentageToZone(mhrPercentage) }

    val displayMode by appViewModel.hrDisplayMode

    val textToDisplay = when(displayMode) {
        0 -> if (hr == 0) "-" else hr.toString()
        1 -> formattedChangeRate
        else ->  "${"%.1f".format(mhrPercentage).replace(',','.')}%"
    }

    val context = LocalContext.current

    val startAngle = 120f
    val endAngle = 235f

    Box(
        modifier = modifier,
        contentAlignment = Alignment.BottomCenter
    ) {
        Row(
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .width(90.dp)
                .height(20.dp)
                .padding(top = 5.dp)
                .clickable {
                    appViewModel.switchHrDisplayMode()
                    VibrateGentle(context)
                }
        ) {
            HeartIcon(
                modifier = Modifier.size(15.dp),
                tint = if (hr == 0) Color.DarkGray else colorsByZone[zone]
            )
            Spacer(modifier = Modifier.width(5.dp))

            if(displayMode != 1){
                Text(
                    text = textToDisplay,
                    textAlign = TextAlign.Center,
                    style = MaterialTheme.typography.caption1,
                    color = if (hr == 0) Color.DarkGray else Color.White
                )
            }else{
                Row(
                    horizontalArrangement = Arrangement.spacedBy(2.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    val textColor = when {
                        confidenceLevel > 0.7f -> MyColors.Green
                        confidenceLevel > 0.3f -> MyColors.Yellow
                        confidenceLevel > 0 -> MyColors.Red
                        else -> Color.White
                    }

                    Text(
                        text =  if (hr == 0) "--" else textToDisplay,
                        textAlign = TextAlign.Center,
                        style = MaterialTheme.typography.caption1,
                        color = if (hr == 0) Color.DarkGray else textColor
                    )
                    if(hr != 0) {
                        val trendIcon = when (hrTrend) {
                            TrendDirection.INCREASING -> Icons.Filled.ArrowUpward
                            TrendDirection.DECREASING -> Icons.Filled.ArrowDownward
                            TrendDirection.STABLE -> Icons.AutoMirrored.Filled.ArrowForward
                            TrendDirection.UNKNOWN -> Icons.Filled.QuestionMark
                        }
                        Icon(
                            imageVector = trendIcon,
                            contentDescription = "Heart rate trend: ${hrTrend.name}",
                            modifier = Modifier.size(15.dp),
                            tint = textColor
                        )
                    }
                }
            }
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

@Composable
fun HeartRateStandard(
    modifier: Modifier = Modifier,
    appViewModel: AppViewModel,
    heartRateChangeViewModel : HeartRateChangeViewModel,
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
            heartRateChangeViewModel.registerHeartRate(hrViewModel.heartRateBpm.value ?: 0)
            delay(1000)
        }
    }

    HeartRateCircularChart(
        modifier = modifier,
        appViewModel = appViewModel,
        heartRateChangeViewModel = heartRateChangeViewModel,
        hr = hr,
        age = userAge,
        lowerBoundMaxHRPercent = lowerBoundMaxHRPercent,
        upperBoundMaxHRPercent = upperBoundMaxHRPercent
    )
}

@Composable
fun HeartRatePolar(
    modifier: Modifier = Modifier,
    appViewModel: AppViewModel,
    heartRateChangeViewModel : HeartRateChangeViewModel,
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
            heartRateChangeViewModel.registerHeartRate(polarViewModel.hrDataState.value ?: 0)
            delay(1000)
        }
    }

    HeartRateCircularChart(
        modifier = modifier,
        appViewModel = appViewModel,
        heartRateChangeViewModel = heartRateChangeViewModel,
        hr = hr,
        age = userAge,
        lowerBoundMaxHRPercent = lowerBoundMaxHRPercent,
        upperBoundMaxHRPercent = upperBoundMaxHRPercent
    )
}