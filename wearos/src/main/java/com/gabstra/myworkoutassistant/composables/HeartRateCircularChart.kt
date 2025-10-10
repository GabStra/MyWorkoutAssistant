package com.gabstra.myworkoutassistant.composables

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.Warning
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.wear.compose.material3.CircularProgressIndicator
import androidx.wear.compose.material3.Icon
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ProgressIndicatorDefaults
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.PolarViewModel
import com.gabstra.myworkoutassistant.data.SensorDataViewModel
import com.gabstra.myworkoutassistant.data.getValueInRange
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.Red
import com.gabstra.myworkoutassistant.shared.colorsByZone
import com.gabstra.myworkoutassistant.shared.getHeartRateFromPercentage
import com.gabstra.myworkoutassistant.shared.getMaxHearthRatePercentage
import com.gabstra.myworkoutassistant.shared.mapPercentageToZone
import com.gabstra.myworkoutassistant.shared.viewmodels.HeartRateChangeViewModel
import com.gabstra.myworkoutassistant.shared.zoneRanges
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

enum class HeartRateStatus {
    HIGHER_THAN_TARGET,
    LOWER_THAN_TARGET,
    OUT_OF_MAX,
}

@Composable
fun HrStatusDialog(
    show: Boolean,
    hr: Int,
    heartRateStatus: HeartRateStatus,
    targetRange: IntRange,
    currentZone: Int,
    colorsByZone: Array<Color>
){
    AnimatedVisibility(
        visible = show,
        enter = fadeIn(animationSpec = tween(500)),
        exit = fadeOut(animationSpec = tween(500))
    ) {
        Dialog(
            onDismissRequest = {  },
            properties = DialogProperties(dismissOnBackPress = false, dismissOnClickOutside = false)
        ) {
            Box(
                modifier = Modifier
                    .background(MaterialTheme.colorScheme.background.copy(alpha = 0.75f))
                    .fillMaxSize()
                    .padding(20.dp),
                contentAlignment = Alignment.Center
            ) {
                Column(
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(5.dp),
                ) {

                    var message = when (heartRateStatus) {
                        HeartRateStatus.HIGHER_THAN_TARGET -> "HR Above Target"
                        HeartRateStatus.LOWER_THAN_TARGET -> "HR Below Target"
                        HeartRateStatus.OUT_OF_MAX -> "Max HR Exceeded"
                    }

                    var icon = when (heartRateStatus) {
                        HeartRateStatus.HIGHER_THAN_TARGET -> Icons.Filled.ArrowUpward
                        HeartRateStatus.LOWER_THAN_TARGET -> Icons.Filled.ArrowDownward
                        HeartRateStatus.OUT_OF_MAX -> Icons.Filled.Warning
                    }

                    Icon(
                        imageVector = icon,
                        contentDescription = "HR Status",
                        modifier = Modifier.size(50.dp),
                        tint = Red
                    )
                    Text(
                        text = message,
                        textAlign = TextAlign.Center,
                        style = MaterialTheme.typography.titleSmall,
                    )

                    Text(
                        text = "(${targetRange.first}-${targetRange.last})",
                        textAlign = TextAlign.Center,
                        style = MaterialTheme.typography.bodyLarge,
                    )

                    Row(
                        modifier = Modifier.padding(top = 5.dp),
                        verticalAlignment = Alignment.Bottom,
                    ){
                        PulsingHeartWithBpm(
                            modifier = Modifier.padding(bottom = 10.dp),
                            bpm = hr,
                            tint = if (hr == 0 || currentZone < 0 || currentZone >= colorsByZone.size) MaterialTheme.colorScheme.onBackground.copy(alpha = 0.3f) else colorsByZone[currentZone],
                            size = 30.dp
                        )
                        Spacer(modifier = Modifier.width(5.dp))
                        Text(
                            text = "$hr",
                            style =  MaterialTheme.typography.numeralMedium,
                            color = if (hr == 0) MaterialTheme.colorScheme.onBackground.copy(alpha = 0.3f) else MaterialTheme.colorScheme.onBackground
                        )
                        Spacer(modifier = Modifier.width(5.dp))
                        Text(
                            modifier = Modifier.padding(bottom = 5.dp),
                            text = "bpm",
                            style = MaterialTheme.typography.bodySmall,
                            color = if (hr == 0) MaterialTheme.colorScheme.onBackground.copy(alpha = 0.3f) else MaterialTheme.colorScheme.onBackground
                        )
                    }
                }
            }
        }
    }
}

@Composable
fun HeartRateCircularChart(
    modifier: Modifier = Modifier,
    appViewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    heartRateChangeViewModel: HeartRateChangeViewModel,
    hr: Int,
    age: Int,
    lowerBoundMaxHRPercent: Float?,
    upperBoundMaxHRPercent: Float?,
) {
    val mhrPercentage = remember(hr, age) { getMaxHearthRatePercentage(hr, age) }
    val scope = rememberCoroutineScope()
    var alertJob by remember { mutableStateOf<Job?>(null) }
    var zoneTrackingJob by remember { mutableStateOf<Job?>(null) }
    var alarmJob by remember { mutableStateOf<Job?>(null) }

    val currentZone by remember(mhrPercentage) {
        derivedStateOf { mapPercentageToZone(mhrPercentage) }
    }

    val alertCooldown = 1000L

    var showHrStatusDialog by remember { mutableStateOf(false) }
    var hrStatus by remember { mutableStateOf(HeartRateStatus.LOWER_THAN_TARGET) }

    LaunchedEffect(Unit) {
        snapshotFlow { showHrStatusDialog }
            .drop(1)
            .collect { isDialogShown ->
                if (isDialogShown) {
                    appViewModel.setDimming(false)
                } else {
                    appViewModel.reEvaluateDimmingForCurrentState()
                }
            }
    }

    fun startAlertJob() {
        alertJob = scope.launch {
            delay(2000)
            while (isActive) {
                hapticsViewModel.doShortImpulse()
                delay(alertCooldown)
            }
        }
    }

    if(lowerBoundMaxHRPercent != null && upperBoundMaxHRPercent != null) {
        var reachedTargetOnce by remember { mutableStateOf(false) }

        val targetRange = remember(lowerBoundMaxHRPercent, upperBoundMaxHRPercent,age) {
            getHeartRateFromPercentage(lowerBoundMaxHRPercent,age)..getHeartRateFromPercentage(upperBoundMaxHRPercent,age)
        }

        LaunchedEffect(mhrPercentage) {
            if(alertJob?.isActive == true) return@LaunchedEffect

            if(mhrPercentage in lowerBoundMaxHRPercent..upperBoundMaxHRPercent) {
                if(alarmJob?.isActive == true) {
                    alarmJob?.cancel()
                    appViewModel.reEvaluateDimmingForCurrentState()
                    showHrStatusDialog = false
                }

                if(zoneTrackingJob?.isActive == true || reachedTargetOnce) {
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

                    if(mhrPercentage < lowerBoundMaxHRPercent) {
                        hrStatus = HeartRateStatus.LOWER_THAN_TARGET
                    } else {
                        hrStatus = HeartRateStatus.HIGHER_THAN_TARGET
                    }

                    showHrStatusDialog = true

                    while (isActive) {
                        hapticsViewModel.doHardVibrationTwiceWithBeep()
                        delay(1000)
                        hapticsViewModel.doHardVibrationTwiceWithBeep()
                        delay(1000)
                        hapticsViewModel.doHardVibrationTwiceWithBeep()
                        delay(5000)
                    }
                }
            }
        }

        HrStatusDialog(showHrStatusDialog,hr, hrStatus,targetRange,currentZone,colorsByZone)
    }

    LaunchedEffect(mhrPercentage) {
        if (mhrPercentage > 100 && alertJob?.isActive == false) {
            startAlertJob()
            hrStatus = HeartRateStatus.OUT_OF_MAX
            showHrStatusDialog = true
            zoneTrackingJob?.cancel()
            alarmJob?.cancel()
        }else if(alertJob?.isActive == true){
            showHrStatusDialog = false
            appViewModel.lightScreenUp()
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

    HeartRateView(modifier,appViewModel,hapticsViewModel,heartRateChangeViewModel, hr, mhrPercentage, currentZone, colorsByZone, lowerBoundMaxHRPercent, upperBoundMaxHRPercent)
}

@Composable
private fun HeartRateDisplay(
    modifier: Modifier = Modifier,
    bpm: Int,
    textToDisplay: String,
    currentZone: Int,
    colorsByZone: Array<Color>,
    displayMode: Int
) {
    Row(
        verticalAlignment = Alignment.Bottom,
        modifier = modifier
    ) {
        Spacer(modifier = Modifier.weight(1f))

        PulsingHeartWithBpm(
            bpm = bpm,
            tint = if (bpm == 0 || currentZone < 0 || currentZone >= colorsByZone.size) MaterialTheme.colorScheme.onBackground.copy(alpha = 0.3f) else colorsByZone[currentZone]
        )
        Spacer(modifier = Modifier.width(5.dp))
        Text(
            text = textToDisplay,
            style = MaterialTheme.typography.labelSmall,
            color = if (bpm == 0) MaterialTheme.colorScheme.onBackground.copy(alpha = 0.3f) else MaterialTheme.colorScheme.onBackground
        )
        Spacer(modifier = Modifier.width(2.5.dp))
        if(bpm != 0 && displayMode == 0){
            Text(
                text = "bpm",
                style = MaterialTheme.typography.bodyExtraSmall,
                color = MaterialTheme.colorScheme.onBackground
            )
        }

        Spacer(modifier = Modifier.weight(1f))
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
    startAngle: Float,
    endAngle: Float,
    lowerBound: Float,
    upperBound: Float,
) {
    if (index !in zoneRanges.indices || index !in colorsByZone.indices) return

    val progressState = remember { mutableFloatStateOf(0f) }

    LaunchedEffect(hr, mhrPercentage, currentZone, lowerBound, upperBound, index) {
        progressState.floatValue = when {
            hr == 0 -> 0f
            currentZone == index -> {
                if (upperBound > lowerBound)
                    ((mhrPercentage - lowerBound) / (upperBound - lowerBound)).coerceIn(0f, 1f)
                else if (mhrPercentage >= lowerBound) 1f else 0f
            }
            currentZone > index -> 1f
            else -> 0f
        }
    }

    CircularProgressIndicator(
        progress = {
            progressState.floatValue
        },
        modifier = modifier,
        colors = ProgressIndicatorDefaults.colors(
            indicatorColor = colorsByZone[index],
            trackColor = MaterialTheme.colorScheme.onBackground.copy(alpha = 0.3f)
        ),
        strokeWidth = 4.dp,
        startAngle = startAngle,
        endAngle = endAngle,
    )
}

fun extractRotationAngles(
    zoneCount: Int,
    zoneRanges: Array<Pair<Float, Float>>,
    lowerBoundMaxHRPercent: Float?,
    upperBoundMaxHRPercent: Float?,
    totalStartAngle: Float,
    segmentArcAngle: Float,
    paddingAngle: Float
): Pair<Float?, Float?> {
    // Sanity check to make sure we have valid zone data
    if (segmentArcAngle <= 0f || zoneCount <= 0) {
        return Pair(null, null)
    }

    var foundLowerBoundRotationAngle: Float? = null
    var foundUpperBoundRotationAngle: Float? = null

    // Check each zone to find where the indicators should be placed
    for (index in 0 until zoneCount) {
        val startAngle = totalStartAngle + index * (segmentArcAngle + paddingAngle)
        val endAngle = startAngle + segmentArcAngle
        val (lowerBound, upperBound) = zoneRanges[index + 1]

        // Check for lower bound indicator
        if (lowerBoundMaxHRPercent != null &&
            lowerBoundMaxHRPercent >= lowerBound && lowerBoundMaxHRPercent < upperBound) {

            val percentageInZone = if (upperBound > lowerBound) {
                ((lowerBoundMaxHRPercent - lowerBound) / (upperBound - lowerBound))
            } else {
                if (lowerBoundMaxHRPercent == lowerBound) 0f else 0f
            }
            foundLowerBoundRotationAngle = getValueInRange(startAngle, endAngle, percentageInZone)
        }

        // Check for upper bound indicator
        if (upperBoundMaxHRPercent != null &&
            upperBoundMaxHRPercent > lowerBound && upperBoundMaxHRPercent <= upperBound) {

            val percentageInZone = if (upperBound > lowerBound) {
                ((upperBoundMaxHRPercent - lowerBound) / (upperBound - lowerBound))
            } else {
                if (upperBoundMaxHRPercent == lowerBound) 0f else 0f
            }
            foundUpperBoundRotationAngle = getValueInRange(startAngle, endAngle, percentageInZone)
        }
    }

    return Pair(foundLowerBoundRotationAngle, foundUpperBoundRotationAngle)
}

@OptIn(ExperimentalHorologistApi::class, ExperimentalFoundationApi::class)
@Composable
private fun HeartRateView(
    modifier: Modifier,
    appViewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    heartRateChangeViewModel: HeartRateChangeViewModel,
    hr: Int,
    mhrPercentage: Float,
    currentZone: Int,
    colorsByZone: Array<Color>,
    lowerBoundMaxHRPercent: Float?,
    upperBoundMaxHRPercent: Float?,
) {
    val displayMode by appViewModel.hrDisplayMode

    val textToDisplay by remember(hr, mhrPercentage) {
        derivedStateOf {
            if (hr == 0) { "-" }
            else{
                when (displayMode) {
                    0 -> hr.toString()
                    1 -> "${"%.1f".format(mhrPercentage).replace(',', '.')}%"
                    else -> throw IllegalArgumentException("Invalid display mode: $displayMode")
                }
            }
        }
    }

    val zoneCount = colorsByZone.size - 1
    val totalStartAngle = 130f
    val totalEndAngle = 230f
    val paddingAngle = 1f

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
            hapticsViewModel.doGentleVibration()
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
                .clickable(onClick = onSwitchClick, enabled = hr != 0)
                .padding(bottom = 5.dp),
            bpm = hr,
            textToDisplay = textToDisplay,
            currentZone = currentZone,
            colorsByZone = colorsByZone,
            displayMode = displayMode
        )

        val (lowerBoundRotationAngle, upperBoundRotationAngle) = extractRotationAngles(
            zoneCount = zoneCount,
            zoneRanges = zoneRanges,
            lowerBoundMaxHRPercent = lowerBoundMaxHRPercent,
            upperBoundMaxHRPercent = upperBoundMaxHRPercent,
            totalStartAngle = totalStartAngle,
            segmentArcAngle = segmentArcAngle,
            paddingAngle = paddingAngle
        )

        if (segmentArcAngle > 0f && zoneCount > 0) {
            for (index in 0 until zoneCount) {

                val startAngle = totalStartAngle + index * (segmentArcAngle + paddingAngle)
                val endAngle = startAngle + segmentArcAngle

                val (lowerBound, upperBound) = zoneRanges[index + 1]

                ZoneSegment(
                    modifier = Modifier.fillMaxSize(),
                    index = index + 1,
                    currentZone = currentZone,
                    hr = hr,
                    mhrPercentage = mhrPercentage,
                    zoneRanges = zoneRanges,
                    colorsByZone = colorsByZone,
                    startAngle = startAngle,
                    endAngle = endAngle,
                    lowerBound = lowerBound,
                    upperBound = upperBound
                )
            }
        }

        if(lowerBoundRotationAngle != null && upperBoundRotationAngle != null){

            var inBounds = remember(mhrPercentage) { mhrPercentage in lowerBoundMaxHRPercent!!..upperBoundMaxHRPercent!! }

            RotatingIndicator(lowerBoundRotationAngle, if(inBounds) Green else MaterialTheme.colorScheme.onBackground.copy(alpha = 0.3f))
            RotatingIndicator(upperBoundRotationAngle, if(inBounds) Red else MaterialTheme.colorScheme.onBackground.copy(alpha = 0.3f))
        }
    }
}

@Composable
fun HeartRateStandard(
    modifier: Modifier = Modifier,
    appViewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
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
        hapticsViewModel = hapticsViewModel,
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
    hapticsViewModel: HapticsViewModel,
    heartRateChangeViewModel : HeartRateChangeViewModel,
    polarViewModel: PolarViewModel,
    userAge : Int,
    lowerBoundMaxHRPercent: Float?,
    upperBoundMaxHRPercent: Float?,
) {
    val hrData by polarViewModel.hrBpm.collectAsState()
    val hr = hrData ?: 0

    LaunchedEffect(Unit) {
        while (true) {
            appViewModel.registerHeartBeat(polarViewModel.hrBpm.value ?: 0)
            heartRateChangeViewModel.registerHeartRate(polarViewModel.hrBpm.value ?: 0)
            delay(1000)
        }
    }

    HeartRateCircularChart(
        modifier = modifier,
        appViewModel = appViewModel,
        hapticsViewModel = hapticsViewModel,
        heartRateChangeViewModel = heartRateChangeViewModel,
        hr = hr,
        age = userAge,
        lowerBoundMaxHRPercent = lowerBoundMaxHRPercent,
        upperBoundMaxHRPercent = upperBoundMaxHRPercent
    )
}