package com.gabstra.myworkoutassistant.composables

import android.content.Context
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.SensorsOff
import androidx.compose.material.icons.filled.Warning
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathOperation
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.PlatformTextStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.min
import androidx.wear.compose.material3.CircularProgressIndicator
import androidx.wear.compose.material3.Icon
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ProgressIndicatorDefaults
import androidx.wear.compose.material3.Text
import androidx.wear.tooling.preview.devices.WearDevices
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsHelper
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.PolarViewModel
import com.gabstra.myworkoutassistant.data.SensorDataViewModel
import com.gabstra.myworkoutassistant.data.getValueInRange
import com.gabstra.myworkoutassistant.data.truncate
import com.gabstra.myworkoutassistant.presentation.theme.baseline
import com.gabstra.myworkoutassistant.presentation.theme.darkScheme
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.Red
import com.gabstra.myworkoutassistant.shared.colorsByZone
import com.gabstra.myworkoutassistant.shared.getHeartRateFromPercentage
import com.gabstra.myworkoutassistant.shared.getMaxHearthRatePercentage
import com.gabstra.myworkoutassistant.shared.getZoneFromPercentage
import com.gabstra.myworkoutassistant.shared.viewmodels.HeartRateChangeViewModel
import com.gabstra.myworkoutassistant.shared.zoneRanges
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlin.math.PI

enum class HeartRateStatus {
    HIGHER_THAN_TARGET,
    LOWER_THAN_TARGET,
    OUT_OF_MAX,
}

@Composable
fun HrTargetGlowEffect(
    isVisible: Boolean,
    modifier: Modifier = Modifier
) {
    val density = LocalDensity.current
    val infiniteTransition = rememberInfiniteTransition(label = "glow")
    val glowAlpha by infiniteTransition.animateFloat(
        initialValue = 0.3f,
        targetValue = 0.8f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 1000, delayMillis = 0),
            repeatMode = RepeatMode.Reverse
        ),
        label = "glowAlpha"
    )

    val visibilityAlpha by animateFloatAsState(
        targetValue = if (isVisible) 1f else 0f,
        animationSpec = tween(durationMillis = 300),
        label = "visibilityAlpha"
    )

    if (isVisible || visibilityAlpha > 0f) {
        BoxWithConstraints(
            modifier = modifier
                .fillMaxSize()
        ) {
            val diameter = min(maxWidth, maxHeight)
            val radiusPx = with(density) { (diameter / 2f).toPx() }
            val center = Offset(radiusPx, radiusPx)
            val glowWidth = with(density) { 15.dp.toPx() }

            Canvas(
                modifier = Modifier
                    .fillMaxSize()
                    .alpha(visibilityAlpha)
            ) {
                if (isVisible) {
                    // Draw circular glow border with radial fade inward
                    val outerRadius = radiusPx
                    val fadeDistance = glowWidth * 1.5f // Fade distance proportional to glow width
                    val innerRadius = (outerRadius - fadeDistance).coerceAtLeast(0f)
                    
                    // Calculate gradient stops (0.0 = center, 1.0 = edge)
                    // We want red at the outer edge and transparent at inner radius
                    val innerStop = if (outerRadius > 0f) innerRadius / outerRadius else 0f
                    val redColor = Red.copy(alpha = glowAlpha * visibilityAlpha)
                    
                    // Create radial gradient: red at outer edge, transparent at inner radius
                    val gradient = Brush.radialGradient(
                        innerStop to Color.Transparent,
                        1.0f to redColor,
                        center = center,
                        radius = outerRadius
                    )
                    
                    // Draw ring shape using path
                    val ringPath = Path().apply {
                        // Outer circle
                        addOval(
                            Rect(
                                center.x - outerRadius,
                                center.y - outerRadius,
                                center.x + outerRadius,
                                center.y + outerRadius
                            )
                        )
                        // Inner circle (counter-clockwise to create hole)
                        addOval(
                            Rect(
                                center.x - innerRadius,
                                center.y - innerRadius,
                                center.x + innerRadius,
                                center.y + innerRadius
                            )
                        )
                        fillType = androidx.compose.ui.graphics.PathFillType.EvenOdd
                    }
                    
                    // Draw the ring with radial gradient
                    drawPath(
                        path = ringPath,
                        brush = gradient
                    )
                }
            }
        }
    }
}

@Composable
fun HrStatusBadge(
    hrStatus: HeartRateStatus?,
    modifier: Modifier = Modifier
) {
    // Store last non-null status so badge content never dereferences null during recomposition or exit animation.
    var lastHrStatus by remember { mutableStateOf<HeartRateStatus?>(null) }
    LaunchedEffect(hrStatus) {
        if (hrStatus != null) lastHrStatus = hrStatus
    }
    AnimatedVisibility(
        visible = hrStatus != null,
        enter = fadeIn(animationSpec = tween(durationMillis = 300)),
        exit = fadeOut(animationSpec = tween(durationMillis = 300))
    ) {
        val status = lastHrStatus
        if (status != null) {
            val message = when (status) {
                HeartRateStatus.HIGHER_THAN_TARGET -> "HR Above Target"
                HeartRateStatus.LOWER_THAN_TARGET -> "HR Below Target"
                HeartRateStatus.OUT_OF_MAX -> "Max HR Exceeded"
            }
            val icon = when (status) {
                HeartRateStatus.HIGHER_THAN_TARGET -> Icons.Filled.ArrowUpward
                HeartRateStatus.LOWER_THAN_TARGET -> Icons.Filled.ArrowDownward
                HeartRateStatus.OUT_OF_MAX -> Icons.Filled.Warning
            }
            Box(
                modifier = modifier
                    .fillMaxWidth()
                    .padding(top = 25.dp),
                contentAlignment = Alignment.TopCenter
            ) {
                Box(
                    modifier = Modifier
                        .background(
                            color = MaterialTheme.colorScheme.background,
                            shape = RoundedCornerShape(12.dp)
                        )
                        .border(
                            BorderStroke(1.dp, Red),
                            shape = RoundedCornerShape(12.dp)
                        )
                        .padding(10.dp)
                ) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Icon(
                            imageVector = icon,
                            contentDescription = "HR Status",
                            modifier = Modifier.size(15.dp),
                            tint = Red
                        )
                        Spacer(modifier = Modifier.size(5.dp))
                        Text(
                            text = message,
                            style = MaterialTheme.typography.bodySmall,
                            color = Red,
                            textAlign = TextAlign.Center
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
    zoneSegmentsModifier: Modifier = Modifier,
    heartRateDisplayModifier: Modifier = Modifier,
    appViewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    heartRateChangeViewModel: HeartRateChangeViewModel,
    hr: Int,
    age: Int,
    measuredMaxHeartRate: Int? = null,
    restingHeartRate: Int? = null,
    lowerBoundMaxHRPercent: Float?,
    upperBoundMaxHRPercent: Float?,
    centerReadoutOnScreen: Boolean = false,
    onHrStatusChange: ((HeartRateStatus?) -> Unit)? = null,
) {
    val mhrPercentage = remember(hr, age, measuredMaxHeartRate, restingHeartRate) {
        getMaxHearthRatePercentage(hr, age, measuredMaxHeartRate, restingHeartRate)
    }
    val scope = rememberWearCoroutineScope()
    var alertJob by remember { mutableStateOf<Job?>(null) }
    var zoneTrackingJob by remember { mutableStateOf<Job?>(null) }
    var alarmJob by remember { mutableStateOf<Job?>(null) }

    val currentZone by remember(mhrPercentage) {
        derivedStateOf { getZoneFromPercentage(mhrPercentage) }
    }

    val alertCooldown = 1000L

    var hrStatus by remember { mutableStateOf<HeartRateStatus?>(null) }

    fun startAlertJob() {
        alertJob = scope.launch {
            delay(2000)
            while (isActive) {
                hapticsViewModel.doShortImpulse()
                delay(alertCooldown)
            }
        }
    }

    if (lowerBoundMaxHRPercent != null && upperBoundMaxHRPercent != null) {
        var reachedTargetOnce by remember { mutableStateOf(false) }

        LaunchedEffect(mhrPercentage) {
            if (alertJob?.isActive == true) return@LaunchedEffect

            if (mhrPercentage in lowerBoundMaxHRPercent..upperBoundMaxHRPercent) {
                if (alarmJob?.isActive == true) {
                    alarmJob?.cancel()
                    hrStatus = null
                    onHrStatusChange?.invoke(null)
                }

                if (zoneTrackingJob?.isActive == true || reachedTargetOnce) {
                    return@LaunchedEffect
                }

                zoneTrackingJob = scope.launch {
                    delay(5000)
                    reachedTargetOnce = true
                }
            } else {
                zoneTrackingJob?.cancel()

                if (!reachedTargetOnce || alarmJob?.isActive == true) {
                    return@LaunchedEffect
                }

                alarmJob = scope.launch {
                    delay(5000)

                    val newStatus = if (mhrPercentage < lowerBoundMaxHRPercent) {
                        HeartRateStatus.LOWER_THAN_TARGET
                    } else {
                        HeartRateStatus.HIGHER_THAN_TARGET
                    }
                    hrStatus = newStatus
                    onHrStatusChange?.invoke(newStatus)

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

        // Update callback when status changes
        LaunchedEffect(hrStatus) {
            onHrStatusChange?.invoke(hrStatus)
        }
    }

    LaunchedEffect(mhrPercentage) {
        if (mhrPercentage > 100 && alertJob?.isActive == false) {
            startAlertJob()
            hrStatus = HeartRateStatus.OUT_OF_MAX
            onHrStatusChange?.invoke(HeartRateStatus.OUT_OF_MAX)
            zoneTrackingJob?.cancel()
            alarmJob?.cancel()
        } else if (alertJob?.isActive == true && mhrPercentage <= 100) {
            hrStatus = null
            onHrStatusChange?.invoke(null)
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

    HeartRateView(
        modifier,
        appViewModel,
        hapticsViewModel,
        heartRateChangeViewModel,
        hr,
        mhrPercentage,
        currentZone,
        colorsByZone,
        lowerBoundMaxHRPercent,
        upperBoundMaxHRPercent,
        zoneSegmentsModifier,
        heartRateDisplayModifier
    )
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
    val textWidth = if(displayMode == 0){
        25.dp
    }else{
        50.dp
    }

    // Zone chip with black background, colored border, and colored text
    val chipBorderColor = colorsByZone[currentZone]

    val zoneText = "Z$currentZone"
    val shape = RoundedCornerShape(12.dp)

    val heartColor = if (bpm == 0)
        MediumDarkGray
    else
        colorsByZone[currentZone]


    Row(
        modifier = modifier,
    ) {
        Spacer(modifier = Modifier.weight(1f))
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(5.dp)
        ){
            PulsingHeartWithBpm(
                bpm = bpm,
                tint = heartColor
            )

            Row{
                Text(
                    modifier = Modifier.alignByBaseline().widthIn(min = textWidth),
                    text = textToDisplay,
                    textAlign = TextAlign.End,
                    style = MaterialTheme.typography.labelMedium,
                    color = if (bpm == 0) MediumDarkGray else MaterialTheme.colorScheme.onBackground
                )

                if (bpm != 0 && displayMode == 0) {
                    Spacer(modifier = Modifier.size(5.dp))
                    Text(
                        modifier = Modifier.alignByBaseline(),
                        text = "bpm",
                        style = MaterialTheme.typography.bodyExtraSmall,
                        color = MaterialTheme.colorScheme.onBackground
                    )
                }
            }
            if(bpm != 0){
                Box(
                    modifier = Modifier
                        .border(BorderStroke(1.dp, chipBorderColor), shape)
                        .background(
                            color = MaterialTheme.colorScheme.background,
                            shape = shape
                        )
                        .width(30.dp)

                    ,
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        modifier = Modifier.padding(2.5.dp),
                        text = zoneText,
                        textAlign = TextAlign.Center,
                        style = MaterialTheme.typography.labelSmall.copy(platformStyle = PlatformTextStyle(
                            includeFontPadding = false
                        )
                        ),
                        color = chipBorderColor
                    )
                }
            }
        }

        Spacer(modifier = Modifier.weight(1f))
    }
}

@Composable
private fun TargetRangeArc(
    modifier: Modifier = Modifier,
    startAngle: Float,
    endAngle: Float,
    color: Color,
    strokeWidth: Dp,
    borderWidth: Dp,
    innerBorderWidth: Dp,
) {
    val backgroundColor = MaterialTheme.colorScheme.background

    fun annularArcPath(
        center: Offset,
        outerRadius: Float,
        innerRadius: Float,
        start: Float,
        end: Float,
        roundCaps: Boolean = true
    ): Path {
        val sweep = end - start
        if (outerRadius <= 0f || innerRadius <= 0f || innerRadius >= outerRadius || sweep == 0f) {
            return Path()
        }

        val outerRect = Rect(
            center.x - outerRadius,
            center.y - outerRadius,
            center.x + outerRadius,
            center.y + outerRadius
        )
        val innerRect = Rect(
            center.x - innerRadius,
            center.y - innerRadius,
            center.x + innerRadius,
            center.y + innerRadius
        )

        val centerlineRadius = (outerRadius + innerRadius) / 2f
        val capRadius = (outerRadius - innerRadius) / 2f

        val ring = Path().apply {
            fillType = androidx.compose.ui.graphics.PathFillType.NonZero
            arcTo(outerRect, start, sweep, false)
            arcTo(innerRect, start + sweep, -sweep, false)
            close()
        }

        if (!roundCaps) return ring
        if (capRadius <= 0f) return ring


        fun endpointCapPath(angleDeg: Float): Path {
            val angleRad = Math.toRadians(angleDeg.toDouble())
            val capCenter = Offset(
                x = center.x + (kotlin.math.cos(angleRad) * centerlineRadius).toFloat(),
                y = center.y + (kotlin.math.sin(angleRad) * centerlineRadius).toFloat()
            )

            return Path().apply {
                addOval(
                    Rect(
                        capCenter.x - capRadius,
                        capCenter.y - capRadius,
                        capCenter.x + capRadius,
                        capCenter.y + capRadius
                    )
                )
            }
        }

        val startCap = endpointCapPath(start)
        val endCap = endpointCapPath(start + sweep)
        return Path.combine(
            PathOperation.Union,
            Path.combine(PathOperation.Union, ring, startCap),
            endCap
        )
    }

    Canvas(modifier = modifier) {
        val diameterPx = size.minDimension
        if (diameterPx <= 0f) return@Canvas

        val center = Offset(size.width / 2f, size.height / 2f)
        val outerRadius = diameterPx / 2f

        val strokePx = strokeWidth.toPx()
        val borderPx = borderWidth.toPx()
        val innerBorderPx = innerBorderWidth.toPx()
        val nudgePx = 2.dp.toPx()

        if (strokePx <= 0f || borderPx < 0f || innerBorderPx < 0f) return@Canvas

        fun pxToDegrees(gapPx: Float): Float = (gapPx / (PI.toFloat() * diameterPx)) * 360f

        val nudgeDeg = pxToDegrees(nudgePx)
        val s = startAngle - nudgeDeg
        val e = endAngle + nudgeDeg

        val outerExtraDeg = pxToDegrees(  2.dp.toPx())
        val innerMaskExtraDeg = pxToDegrees(innerBorderPx)

        val outerExpanded = annularArcPath(
            center = center,
            outerRadius = outerRadius,
            innerRadius = outerRadius - strokePx,
            start = s + pxToDegrees(innerBorderPx) - outerExtraDeg,
            end = e - pxToDegrees(innerBorderPx) + outerExtraDeg,
            roundCaps = true
        )

        val middleOuter = outerRadius - borderPx
        val middleStroke = strokePx - borderPx * 2f
        val middle = annularArcPath(
            center = center,
            outerRadius = middleOuter,
            innerRadius = middleOuter - middleStroke,
            start = startAngle + innerMaskExtraDeg,
            end = endAngle - innerMaskExtraDeg,
            roundCaps = true
        )

        val outerBorder = Path.combine(PathOperation.Difference, outerExpanded, middle)

        val colorExpanded = annularArcPath(
            center = center,
            outerRadius = outerRadius,
            innerRadius = outerRadius - strokePx,
            start = s + pxToDegrees(innerBorderPx),
            end = e - pxToDegrees(innerBorderPx),
            roundCaps = true
        )

        val innerInset = borderPx - innerBorderPx
        val innerMaskOuter = outerRadius - innerInset
        val innerMaskStroke = strokePx - borderPx * 2f + innerBorderPx * 2f
        val innerMask = annularArcPath(
            center = center,
            outerRadius = innerMaskOuter,
            innerRadius = innerMaskOuter - innerMaskStroke,
            start = s + pxToDegrees(innerBorderPx),
            end = e - pxToDegrees(innerBorderPx),
            roundCaps = true
        )

        val colorWithoutMiddle = Path.combine(PathOperation.Difference, colorExpanded, middle)
        val finalColor = Path.combine(PathOperation.Difference, colorWithoutMiddle, innerMask)

        //drawPath(path = outerExpanded, color = Color.Magenta)
        drawPath(path = outerBorder, color = backgroundColor)
        drawPath(path = finalColor, color = color)
        //drawPath(path = middle, color = Color.Magenta)
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

    fun computeProgress(): Float = when {
        hr == 0 -> 0f
        currentZone == index -> {
            if (upperBound > lowerBound)
                ((mhrPercentage - lowerBound) / (upperBound - lowerBound)).coerceIn(0f, 1f)
            else if (mhrPercentage >= lowerBound) 1f else 0f
        }

        currentZone > index -> 1f
        else -> 0f
    }

    val progressState = remember { mutableFloatStateOf(computeProgress()) }

    LaunchedEffect(hr, mhrPercentage, currentZone, lowerBound, upperBound, index) {
        progressState.floatValue = computeProgress()
    }

    val trackColor = remember(currentZone, index, hr) {
        if (currentZone == index && hr > 0) {
            colorsByZone[index].copy(alpha = 0.35f)
        } else {
            MediumDarkGray
        }
    }

    CircularProgressIndicator(
        progress = {
            progressState.floatValue
        },
        modifier = modifier,
        colors = ProgressIndicatorDefaults.colors(
            indicatorColor = colorsByZone[index],
            trackColor = trackColor
        ),
        strokeWidth = 4.dp,
        startAngle = startAngle,
        endAngle = endAngle
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
            lowerBoundMaxHRPercent >= lowerBound && lowerBoundMaxHRPercent < upperBound
        ) {

            val percentageInZone = if (upperBound > lowerBound) {
                ((lowerBoundMaxHRPercent - lowerBound) / (upperBound - lowerBound))
            } else {
                if (lowerBoundMaxHRPercent == lowerBound) 0f else 0f
            }
            foundLowerBoundRotationAngle = getValueInRange(startAngle, endAngle, percentageInZone)
        }

        // Check for upper bound indicator
        if (upperBoundMaxHRPercent != null &&
            upperBoundMaxHRPercent > lowerBound && upperBoundMaxHRPercent <= upperBound
        ) {

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

fun extractCurrentHrRotationAngle(
    zoneCount: Int,
    zoneRanges: Array<Pair<Float, Float>>,
    mhrPercentage: Float?,
    totalStartAngle: Float,
    segmentArcAngle: Float,
    paddingAngle: Float
): Float? {
    if (segmentArcAngle <= 0f || zoneCount <= 0 || mhrPercentage == null) return null

    for (index in 0 until zoneCount) {
        val startAngle = totalStartAngle + index * (segmentArcAngle + paddingAngle)
        val endAngle = startAngle + segmentArcAngle
        val (lowerBound, upperBound) = zoneRanges[index + 1]

        if (mhrPercentage.truncate(1) in lowerBound.truncate(1)..upperBound.truncate(1)) {
            val percentageInZone = if (upperBound > lowerBound) {
                ((mhrPercentage- lowerBound) / (upperBound - lowerBound)).coerceIn(0f, 1f)
            } else 0f

            return getValueInRange(startAngle, endAngle, percentageInZone)
        }
    }

    return null
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
    zoneSegmentsModifier: Modifier,
    heartRateDisplayModifier: Modifier
) {
    val screenState by appViewModel.screenState.collectAsState()
    val displayMode = screenState.hrDisplayMode

    val textToDisplay by remember(hr, mhrPercentage, displayMode) {
        derivedStateOf {
            when (displayMode) {
                0 -> hr.toString()
                1 -> "${"%.1f".format(mhrPercentage).replace(',', '.')}%"
                else -> throw IllegalArgumentException("Invalid display mode: $displayMode")
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

    Box(modifier = modifier) {
        Box(
            modifier = Modifier.fillMaxSize(),
            contentAlignment = Alignment.BottomCenter
        ) {

            if (hr == 0) {
                Icon(
                    imageVector = Icons.Filled.SensorsOff,
                    contentDescription = "Disconnected",
                    modifier = Modifier
                        .size(15.dp)
                        .offset(y = (-15).dp)
                        .then(heartRateDisplayModifier),
                    tint = MediumDarkGray
                )
            } else {
                HeartRateDisplay(
                    modifier = Modifier
                        .width(120.dp)
                        .height(25.dp)
                        .offset(y = (-15).dp)
                        .clickable(onClick = onSwitchClick)
                        .then(heartRateDisplayModifier),
                    bpm = hr,
                    textToDisplay = textToDisplay,
                    currentZone = currentZone,
                    colorsByZone = colorsByZone,
                    displayMode = displayMode
                )
            }

            val (lowerBoundRotationAngle, upperBoundRotationAngle) = extractRotationAngles(
                zoneCount = zoneCount,
                zoneRanges = zoneRanges,
                lowerBoundMaxHRPercent = lowerBoundMaxHRPercent,
                upperBoundMaxHRPercent = upperBoundMaxHRPercent,
                totalStartAngle = totalStartAngle,
                segmentArcAngle = segmentArcAngle,
                paddingAngle = paddingAngle
            )

            val currentHrRotationAngle = extractCurrentHrRotationAngle(
                zoneCount = zoneCount,
                zoneRanges = zoneRanges,
                mhrPercentage = mhrPercentage,
                totalStartAngle = totalStartAngle,
                segmentArcAngle = segmentArcAngle,
                paddingAngle = paddingAngle
            )

            if (segmentArcAngle > 0f && zoneCount > 0) {
                for (index in 0 until zoneCount) {

                val startAngle = totalStartAngle + index * (segmentArcAngle + paddingAngle)
                val endAngle = startAngle + segmentArcAngle

                val (lowerBound, upperBound) = zoneRanges[index + 1]

                    key(hr) {
                        ZoneSegment(
                            modifier = Modifier
                                .fillMaxSize()
                                .padding(10.dp)
                                .then(zoneSegmentsModifier),
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
            }

            if (lowerBoundRotationAngle != null && upperBoundRotationAngle != null) {
                val inBounds = remember(
                    hr,
                    mhrPercentage,
                    lowerBoundMaxHRPercent,
                    upperBoundMaxHRPercent,
                    screenState.userAge,
                    screenState.measuredMaxHeartRate,
                    screenState.restingHeartRate
                ) {
                    mhrPercentage in lowerBoundMaxHRPercent!!..upperBoundMaxHRPercent!!
                }

                TargetRangeArc(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(3.dp)
                        .then(zoneSegmentsModifier),
                    startAngle = lowerBoundRotationAngle,
                    endAngle = upperBoundRotationAngle,
                    color = if (inBounds) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.primary.copy(alpha = 0.35f),
                    strokeWidth = 18.dp,
                    borderWidth = 6.dp,
                    innerBorderWidth = 4.dp
                )
            }

            /*
        if (currentHrRotationAngle != null) {
            /*
            val animatedAngle by animateFloatAsState(

                targetValue = currentHrRotationAngle,
                animationSpec = tween(durationMillis = 300),
                label = "HeartRateIndicatorAngle"
            )*/

            Box(modifier = Modifier
                .fillMaxSize()
                .padding(3.dp)
            ) {
                HeartRateIndicator(
                    currentHrRotationAngle,
                    MaterialTheme.colorScheme.onBackground,
                    bubbleSize = 18.dp,
                    borderWidth = 2.dp
                )
            }
        }
            */
        }
    }
}

@Composable
fun HeartRateStandard(
    modifier: Modifier = Modifier,
    zoneSegmentsModifier: Modifier = Modifier,
    heartRateDisplayModifier: Modifier = Modifier,
    appViewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    heartRateChangeViewModel: HeartRateChangeViewModel,
    hrViewModel: SensorDataViewModel,
    userAge: Int,
    measuredMaxHeartRate: Int? = null,
    restingHeartRate: Int? = null,
    lowerBoundMaxHRPercent: Float?,
    upperBoundMaxHRPercent: Float?,
    centerReadoutOnScreen: Boolean = false,
    readoutAnchorOffsetX: Dp = 0.dp,
    onHrStatusChange: ((HeartRateStatus?) -> Unit)? = null,
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
        zoneSegmentsModifier = zoneSegmentsModifier,
        heartRateDisplayModifier = heartRateDisplayModifier,
        appViewModel = appViewModel,
        hapticsViewModel = hapticsViewModel,
        heartRateChangeViewModel = heartRateChangeViewModel,
        hr = hr,
        age = userAge,
        measuredMaxHeartRate = measuredMaxHeartRate,
        restingHeartRate = restingHeartRate,
        lowerBoundMaxHRPercent = lowerBoundMaxHRPercent,
        upperBoundMaxHRPercent = upperBoundMaxHRPercent,
        centerReadoutOnScreen = centerReadoutOnScreen,
        onHrStatusChange = onHrStatusChange
    )
}

@Composable
fun HeartRatePolar(
    modifier: Modifier = Modifier,
    zoneSegmentsModifier: Modifier = Modifier,
    heartRateDisplayModifier: Modifier = Modifier,
    appViewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    heartRateChangeViewModel: HeartRateChangeViewModel,
    polarViewModel: PolarViewModel,
    userAge: Int,
    measuredMaxHeartRate: Int? = null,
    restingHeartRate: Int? = null,
    lowerBoundMaxHRPercent: Float?,
    upperBoundMaxHRPercent: Float?,
    centerReadoutOnScreen: Boolean = false,
    onHrStatusChange: ((HeartRateStatus?) -> Unit)? = null,
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
        zoneSegmentsModifier = zoneSegmentsModifier,
        heartRateDisplayModifier = heartRateDisplayModifier,
        appViewModel = appViewModel,
        hapticsViewModel = hapticsViewModel,
        heartRateChangeViewModel = heartRateChangeViewModel,
        hr = hr,
        age = userAge,
        measuredMaxHeartRate = measuredMaxHeartRate,
        restingHeartRate = restingHeartRate,
        lowerBoundMaxHRPercent = lowerBoundMaxHRPercent,
        upperBoundMaxHRPercent = upperBoundMaxHRPercent,
        centerReadoutOnScreen = centerReadoutOnScreen,
        onHrStatusChange = onHrStatusChange
    )
}

// Create ViewModels outside composable to avoid "Constructing a view model in a composable" warning
private val previewAppViewModel = AppViewModel()
private val previewHeartRateChangeViewModel = HeartRateChangeViewModel()

// Helper function to create HapticsViewModel outside composable context
private fun createPreviewHapticsViewModel(context: Context): HapticsViewModel {
    return HapticsViewModel(context, HapticsHelper(context))
}

@Preview(device = WearDevices.LARGE_ROUND, showBackground = true)
@Composable
private fun HeartRateCircularChartPreview() {
    //previewAppViewModel.switchHrDisplayMode()
    val context = LocalContext.current
    val hapticsViewModel = remember(context) { createPreviewHapticsViewModel(context) }
    MaterialTheme(
        colorScheme = darkScheme,
        typography = baseline,
    ) {
        HeartRateCircularChart(
            modifier = Modifier.fillMaxSize(),
            appViewModel = previewAppViewModel,
            hapticsViewModel = hapticsViewModel,
            heartRateChangeViewModel = previewHeartRateChangeViewModel,
            hr = getHeartRateFromPercentage(98f, 30),
            age = 30,
            lowerBoundMaxHRPercent = 65f,
            upperBoundMaxHRPercent = 75f
        )
    }
}
