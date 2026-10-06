package com.gabstra.myworkoutassistant.workout

import androidx.compose.animation.core.FastOutLinearInEasing
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.keyframes
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.colorsByZone
import com.gabstra.myworkoutassistant.shared.getMaxHearthRatePercentage
import com.gabstra.myworkoutassistant.shared.getZoneFromPercentage
import com.gabstra.myworkoutassistant.shared.zoneRanges

private val MobileHeartSize = 24.dp
private val MobileZoneBadgeWidth = 44.dp
private val MobileSegmentHeight = 8.dp
private val MobileSegmentGap = 5.dp
private val MobileChartHeight = 32.dp

@Composable
fun HeartRateLinearChart(
    heartRate: Int,
    age: Int,
    modifier: Modifier = Modifier,
    measuredMaxHeartRate: Int? = null,
    restingHeartRate: Int? = null,
    lowerBoundMaxHRPercent: Float? = null,
    upperBoundMaxHRPercent: Float? = null,
) {
    val heartRatePercentage = remember(heartRate, age, measuredMaxHeartRate, restingHeartRate) {
        getMaxHearthRatePercentage(heartRate, age, measuredMaxHeartRate, restingHeartRate)
    }
    val currentZone = remember(heartRatePercentage) {
        getZoneFromPercentage(heartRatePercentage)
    }
    val activeColor = if (heartRate > 0) colorsByZone[currentZone] else MediumDarkGray
    val zoneBadgeShape = RoundedCornerShape(14.dp)

    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            PulsingHeart(
                bpm = heartRate,
                tint = activeColor,
            )
            Spacer(modifier = Modifier.width(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                val valueColor = if (heartRate > 0) {
                    MaterialTheme.colorScheme.onBackground
                } else {
                    MediumDarkGray
                }
                Text(
                    text = if (heartRate > 0) heartRate.toString() else "--",
                    modifier = Modifier.alignByBaseline(),
                    style = MaterialTheme.typography.headlineSmall,
                    color = valueColor,
                )
                Text(
                    text = "bpm",
                    modifier = Modifier.alignByBaseline(),
                    style = MaterialTheme.typography.bodyMedium,
                    color = valueColor,
                )
            }
            if (heartRate > 0 && currentZone > 0) {
                Spacer(modifier = Modifier.width(10.dp))
                Box(
                    modifier = Modifier
                        .border(BorderStroke(1.dp, activeColor), zoneBadgeShape)
                        .background(MaterialTheme.colorScheme.background, zoneBadgeShape)
                        .width(MobileZoneBadgeWidth)
                        .padding(vertical = 4.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        text = "Z$currentZone",
                        modifier = Modifier.fillMaxWidth(),
                        textAlign = TextAlign.Center,
                        style = MaterialTheme.typography.labelLarge,
                        color = activeColor,
                    )
                }
            }
        }

        val targetIsActive = lowerBoundMaxHRPercent != null &&
            upperBoundMaxHRPercent != null &&
            heartRatePercentage in lowerBoundMaxHRPercent..upperBoundMaxHRPercent
        val targetColor = if (targetIsActive) {
            MaterialTheme.colorScheme.primary
        } else {
            MaterialTheme.colorScheme.primary.copy(alpha = 0.5f)
        }
        val targetSeparationColor = MaterialTheme.colorScheme.background
        Canvas(
            modifier = Modifier
                .fillMaxWidth()
                .height(MobileChartHeight)
                .padding(horizontal = 16.dp),
        ) {
            val trackHeight = MobileSegmentHeight.toPx()
            val trackTop = (size.height - trackHeight) / 2f
            val segmentGap = MobileSegmentGap.toPx()
            val displayedZones = zoneRanges.indices.drop(1)
            val segmentWidth = (size.width - segmentGap * (displayedZones.size - 1)) / displayedZones.size

            displayedZones.forEachIndexed { visibleIndex, zoneIndex ->
                val left = visibleIndex * (segmentWidth + segmentGap)
                val (lowerBound, upperBound) = zoneRanges[zoneIndex]
                val progress = when {
                    heartRate <= 0 -> 0f
                    currentZone > zoneIndex -> 1f
                    currentZone < zoneIndex -> 0f
                    upperBound > lowerBound ->
                        ((heartRatePercentage - lowerBound) / (upperBound - lowerBound)).coerceIn(0f, 1f)
                    heartRatePercentage >= lowerBound -> 1f
                    else -> 0f
                }
                val zoneTrackColor = if (currentZone == zoneIndex && heartRate > 0) {
                    colorsByZone[zoneIndex].copy(alpha = 0.5f)
                } else {
                    MediumDarkGray
                }
                drawRoundRect(
                    color = zoneTrackColor,
                    topLeft = Offset(left, trackTop),
                    size = Size(segmentWidth, trackHeight),
                    cornerRadius = androidx.compose.ui.geometry.CornerRadius(4.dp.toPx()),
                )
                if (progress > 0f) {
                    drawRoundRect(
                        color = colorsByZone[zoneIndex],
                        topLeft = Offset(left, trackTop),
                        size = Size(segmentWidth * progress, trackHeight),
                        cornerRadius = androidx.compose.ui.geometry.CornerRadius(4.dp.toPx()),
                    )
                }
            }

            if (lowerBoundMaxHRPercent != null && upperBoundMaxHRPercent != null) {
                val targetLeft = percentageToTrackX(
                    percentage = minOf(lowerBoundMaxHRPercent, upperBoundMaxHRPercent),
                    segmentWidth = segmentWidth,
                    segmentGap = segmentGap,
                )
                val targetRight = percentageToTrackX(
                    percentage = maxOf(lowerBoundMaxHRPercent, upperBoundMaxHRPercent),
                    segmentWidth = segmentWidth,
                    segmentGap = segmentGap,
                )
                val targetTop = trackTop - 7.dp.toPx()
                val targetSize = Size(
                    width = (targetRight - targetLeft).coerceAtLeast(1.dp.toPx()),
                    height = trackHeight + 14.dp.toPx(),
                )
                val targetCornerRadius = androidx.compose.ui.geometry.CornerRadius(10.dp.toPx())
                drawRoundRect(
                    color = targetSeparationColor,
                    topLeft = Offset(targetLeft, targetTop),
                    size = targetSize,
                    cornerRadius = targetCornerRadius,
                    style = Stroke(width = 8.dp.toPx()),
                )
                drawRoundRect(
                    color = targetColor,
                    topLeft = Offset(targetLeft, targetTop),
                    size = targetSize,
                    cornerRadius = targetCornerRadius,
                    style = Stroke(width = 3.dp.toPx()),
                )
            }

        }
    }
}

private fun percentageToTrackX(
    percentage: Float,
    segmentWidth: Float,
    segmentGap: Float,
): Float {
    val normalizedPercentage = percentage.coerceIn(50f, 100f)
    val zoneOffset = ((normalizedPercentage - 50f) / 10f).coerceIn(0f, 5f)
    val zoneIndex = zoneOffset.toInt().coerceAtMost(4)
    val progressInZone = if (normalizedPercentage >= 100f) 1f else zoneOffset - zoneIndex
    return zoneIndex * (segmentWidth + segmentGap) + segmentWidth * progressInZone
}

@Composable
private fun PulsingHeart(
    bpm: Int,
    tint: Color,
) {
    val scale = if (bpm > 0) {
        val beatDuration = 60_000 / bpm
        val systoleDuration = (beatDuration * 0.33f).toInt()
        rememberInfiniteTransition(label = "heart-transition").animateFloat(
            initialValue = 0.8f,
            targetValue = 1.2f,
            animationSpec = infiniteRepeatable(
                animation = keyframes {
                    durationMillis = beatDuration
                    0.8f at 0 using FastOutLinearInEasing
                    1.2f at systoleDuration using FastOutLinearInEasing
                    0.8f at beatDuration using FastOutSlowInEasing
                },
                repeatMode = RepeatMode.Restart,
            ),
            label = "heart-scale",
        ).value
    } else {
        1f
    }

    Icon(
        imageVector = Icons.Filled.Favorite,
        contentDescription = "Heart",
        modifier = Modifier
            .size(MobileHeartSize)
            .scale(scale),
        tint = tint,
    )
}

@Preview(showBackground = true, backgroundColor = 0xFF000000)
@Composable
private fun HeartRateLinearChartPreview() {
    MaterialTheme {
        HeartRateLinearChart(
            heartRate = 148,
            age = 35,
            lowerBoundMaxHRPercent = 70f,
            upperBoundMaxHRPercent = 80f,
            modifier = Modifier
                .fillMaxWidth()
                .padding(24.dp),
        )
    }
}
