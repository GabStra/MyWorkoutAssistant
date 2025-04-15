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
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.QuestionMark
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.derivedStateOf
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
import com.gabstra.myworkoutassistant.shared.VibrateGentle
import com.gabstra.myworkoutassistant.shared.VibrateShortImpulse
import com.gabstra.myworkoutassistant.shared.VibrateTwiceAndBeep
import com.gabstra.myworkoutassistant.data.getValueInRange
import com.gabstra.myworkoutassistant.presentation.theme.MyColors
import com.gabstra.myworkoutassistant.shared.colorsByZone
import com.gabstra.myworkoutassistant.shared.getMaxHearthRatePercentage
import com.gabstra.myworkoutassistant.shared.mapPercentage
import com.gabstra.myworkoutassistant.shared.mapPercentageToZone
import com.gabstra.myworkoutassistant.shared.viewmodels.HeartRateChangeViewModel
import com.gabstra.myworkoutassistant.shared.viewmodels.HeartRateChangeViewModel.TrendDirection
import com.gabstra.myworkoutassistant.shared.zoneRanges
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import com.google.android.horologist.composables.ProgressIndicatorSegment
import com.google.android.horologist.composables.SegmentedProgressIndicator
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

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

@Composable
private fun HeartRateDisplay(
    modifier: Modifier = Modifier,
    hr: Int,
    displayMode: Int,
    textToDisplay: String,
    currentZone: Int,
    colorsByZone: Array<Color>,
    confidenceLevel: Float,
    hrTrend: TrendDirection,
) {
    Row(
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
        modifier = modifier
    ) {
        HeartIcon(
            modifier = Modifier.size(15.dp),
            tint = if (hr == 0 || currentZone < 0 || currentZone >= colorsByZone.size) Color.DarkGray else colorsByZone[currentZone]
        )
        Spacer(modifier = Modifier.width(5.dp))

        if (displayMode != 1) {
            Text(
                text = textToDisplay,
                textAlign = TextAlign.Center,
                style = MaterialTheme.typography.caption1,
                color = if (hr == 0) Color.DarkGray else Color.White
            )
        } else {
            Row(
                horizontalArrangement = Arrangement.spacedBy(2.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                val textColor by remember(confidenceLevel, hr) {
                    derivedStateOf {
                        when {
                            hr == 0 -> Color.DarkGray
                            confidenceLevel > 0.7f -> MyColors.Green
                            confidenceLevel > 0.3f -> MyColors.Yellow
                            confidenceLevel >= 0f -> MyColors.Red // Include 0 confidence in Red
                            else -> Color.White // Fallback
                        }
                    }
                }

                Text(
                    text = if (hr == 0) "--" else textToDisplay,
                    textAlign = TextAlign.Center,
                    style = MaterialTheme.typography.caption1,
                    color = textColor
                )
                if (hr != 0) {
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
}

@OptIn(ExperimentalHorologistApi::class)
@Composable
private fun ZoneSegment(
    modifier: Modifier = Modifier,
    index: Int,
    currentZone: Int,
    hr: Int,
    mhrPercentage: Float,
    zoneRanges: Array<Pair<Float, Float>>,
    colorsByZone: Array<Color>,
    totalStartAngle: Float,
    segmentArcAngle: Float,
    paddingAngle: Float,
    lowerBoundMaxHRPercent: Float?,
    upperBoundMaxHRPercent: Float?,
) {
    if (index !in zoneRanges.indices || index !in colorsByZone.indices) return

    val (lowerBound, upperBound) = zoneRanges[index]

    val indicatorProgress by remember(hr, currentZone, index, mhrPercentage, lowerBound, upperBound) {
        derivedStateOf {
            when {
                hr == 0 -> 0f
                index == currentZone -> {
                    if (upperBound > lowerBound) {
                        ((mhrPercentage - lowerBound) / (upperBound - lowerBound)).coerceIn(0f, 1f)
                    } else {
                        if (mhrPercentage >= lowerBound) 1f else 0f
                    }
                }
                index < currentZone -> 1f
                else -> 0f
            }
        }
    }

    val trackSegment = remember(colorsByZone, index) {
        ProgressIndicatorSegment(
            weight = 1f,
            indicatorColor = colorsByZone[index]
        )
    }

    val startAngle = totalStartAngle + index * (segmentArcAngle + paddingAngle)
    val endAngle = startAngle + segmentArcAngle

    SegmentedProgressIndicator(
        trackSegments = listOf(trackSegment),
        progress = indicatorProgress,
        modifier = modifier,
        strokeWidth = 4.dp,
        paddingAngle = 0f,
        startAngle = startAngle,
        endAngle = endAngle,
        trackColor = Color.DarkGray,
    )

    // --- Boundary Indicator Logic (Handles within-zone and boundaries correctly) ---

    // Check if the LOWER bound target falls within this zone's range [lower, upper)
    // OR exactly at the upper bound IF this is the last zone [lower, upper]
    val shouldDrawLowerBoundIndicator = lowerBoundMaxHRPercent != null &&
            (lowerBoundMaxHRPercent >= lowerBound && lowerBoundMaxHRPercent < upperBound)


    // Check if the UPPER bound target falls within this zone's range [lower, upper)
    // OR exactly at the upper bound IF this is the last zone [lower, upper]
    val shouldDrawUpperBoundIndicator = upperBoundMaxHRPercent != null &&
            (upperBoundMaxHRPercent > lowerBound && upperBoundMaxHRPercent <= upperBound)


    if (shouldDrawLowerBoundIndicator && lowerBoundMaxHRPercent != null) {
        val lowerBoundRotationAngle by remember(lowerBoundMaxHRPercent, lowerBound, upperBound, startAngle, endAngle) {
            derivedStateOf {
                val percentageInZone = if (upperBound > lowerBound) {
                    ((lowerBoundMaxHRPercent - lowerBound) / (upperBound - lowerBound))
                } else {
                    if (lowerBoundMaxHRPercent == lowerBound) 0f else 0f // Default to 0 if bounds are equal
                }
                getValueInRange(startAngle, endAngle, percentageInZone)
            }
        }
        RotatingIndicator(lowerBoundRotationAngle, MyColors.Green)
    }

    if (shouldDrawUpperBoundIndicator && upperBoundMaxHRPercent != null) {
        val upperBoundRotationAngle by remember(upperBoundMaxHRPercent, lowerBound, upperBound, startAngle, endAngle) {
            derivedStateOf {
                // Calculate percentage *within this specific zone*
                val percentageInZone = if (upperBound > lowerBound) {
                    ((upperBoundMaxHRPercent - lowerBound) / (upperBound - lowerBound))
                } else {
                    // Handle zero-width zone: only possible if target == bound
                    if (upperBoundMaxHRPercent == lowerBound) 0f else 0f // Default to 0 if bounds are equal
                }
                getValueInRange(startAngle, endAngle, percentageInZone)
            }
        }
        RotatingIndicator(upperBoundRotationAngle, MyColors.Red)
    }
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
    val displayMode by appViewModel.hrDisplayMode

    val textToDisplay by remember(hr, mhrPercentage) {
        derivedStateOf {
            when (displayMode) {
                0 -> if (hr == 0) "-" else hr.toString()
                1 -> formattedChangeRate
                else -> "${"%.1f".format(mhrPercentage).replace(',', '.')}%"
            }
        }
    }

    val currentZone by remember(mhrPercentage) {
        derivedStateOf { mapPercentageToZone(mhrPercentage) }
    }

    val zoneCount = colorsByZone.size
    val totalStartAngle = 120f
    val totalEndAngle = 240f
    val paddingAngle = 2f

    val totalArcAngle by remember { derivedStateOf { totalEndAngle - totalStartAngle } }
    val segmentArcAngle by remember(zoneCount, totalArcAngle, paddingAngle) {
        derivedStateOf {
            if (zoneCount > 0) {
                (totalArcAngle - (zoneCount - 1).coerceAtLeast(0) * paddingAngle) / zoneCount
            } else {
                0f
            }
        }
    }

    val context = LocalContext.current
    val onSwitchClick = remember(appViewModel, context) {
        {
            appViewModel.switchHrDisplayMode()
            VibrateGentle(context)
        }
    }

    Box(
        modifier = modifier,
        contentAlignment = Alignment.BottomCenter
    ) {
        HeartRateDisplay(
            modifier = Modifier
                .width(90.dp)
                .height(20.dp)
                .padding(top = 5.dp)
                .clickable(onClick = onSwitchClick),
            hr = hr,
            displayMode = displayMode,
            textToDisplay = textToDisplay,
            currentZone = currentZone,
            colorsByZone = colorsByZone,
            confidenceLevel = confidenceLevel,
            hrTrend = hrTrend
        )

        if (segmentArcAngle > 0f && zoneCount > 0 && zoneRanges.size == zoneCount) {
            for (index in 0 until zoneCount) {
                ZoneSegment(
                    modifier = Modifier.fillMaxSize(),
                    index = index,
                    currentZone = currentZone,
                    hr = hr,
                    mhrPercentage = mhrPercentage,
                    zoneRanges = zoneRanges,
                    colorsByZone = colorsByZone,
                    totalStartAngle = totalStartAngle,
                    segmentArcAngle = segmentArcAngle,
                    paddingAngle = paddingAngle,
                    lowerBoundMaxHRPercent = lowerBoundMaxHRPercent,
                    upperBoundMaxHRPercent = upperBoundMaxHRPercent
                )
            }
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