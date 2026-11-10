package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.heart_rate.HeartRateSessionAnalysis
import com.gabstra.myworkoutassistant.heart_rate.getHeartRateZoneBounds
import com.gabstra.myworkoutassistant.heart_rate.getHeartRateZoneGuideValues
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.colorsByZone
import com.kevinnzou.compose.progressindicator.SimpleProgressIndicator
import kotlin.math.roundToInt

@Composable
fun HeartRateSessionCard(
    title: String,
    analysis: HeartRateSessionAnalysis,
    userAge: Int,
    modifier: Modifier = Modifier,
    measuredMaxHeartRate: Int? = null,
    restingHeartRate: Int? = null,
    caloriesBurned: Int? = null,
    sweatLossMl: Int? = null,
    fluidsToReplaceMl: Int? = null,
    hrvRmssdMs: Double? = null,
    skinTempStartC: Float? = null,
    skinTempMaxC: Float? = null,
    primarySourceLabel: String? = null,
    onInteractionChange: (Boolean) -> Unit = {},
) {
    val zoneBounds = getHeartRateZoneBounds(
        userAge = userAge,
        measuredMaxHeartRate = measuredMaxHeartRate,
        restingHeartRate = restingHeartRate,
    )

    PrimarySurface(modifier = modifier) {
        ExpandableContainer(
            isOpen = true,
            modifier = Modifier.fillMaxWidth(),
            isExpandable = analysis.zoneCounts.isNotEmpty(),
            title = {
                Text(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(10.dp),
                    text = title,
                    color = MaterialTheme.colorScheme.onBackground,
                    style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.SemiBold),
                )
            },
            subContent = {
                val extraSummaries = analysis.extraSummaries
                val showSources = extraSummaries.isNotEmpty()
                if (showSources) {
                    HeartRateSourceLegend(
                        labels = listOf(primarySourceLabel ?: "Primary") +
                            extraSummaries.map { it.label },
                    )
                }
                HeartRateChartContent(
                    modifier = Modifier.fillMaxWidth(),
                    cartesianChartModel = analysis.chartModel,
                    userAge = userAge,
                    measuredMaxHeartRate = measuredMaxHeartRate,
                    restingHeartRate = restingHeartRate,
                    minYBpm = analysis.minChartY,
                    seriesColors = if (showSources) {
                        HeartRateSourceColors.take(1 + extraSummaries.size)
                    } else {
                        null
                    },
                    zoneGuideValuesBpm = getHeartRateZoneGuideValues(
                        userAge = userAge,
                        measuredMaxHeartRate = measuredMaxHeartRate,
                        restingHeartRate = restingHeartRate,
                    ),
                    onInteractionChange = onInteractionChange,
                )

                Spacer(modifier = Modifier.height(10.dp))

                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 10.dp)
                        .padding(bottom = 10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Column(
                        modifier = Modifier.weight(1f),
                        verticalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        Text(
                            text = "Duration: ${formatTime(analysis.durationSeconds)}",
                            color = MaterialTheme.colorScheme.onBackground,
                            style = MaterialTheme.typography.bodyMedium,
                        )
                        if (showSources) {
                            Text(
                                text = "${primarySourceLabel ?: "Primary"}: " +
                                    "${analysis.averageHeartRate} avg · " +
                                    "${analysis.minHeartRate}–${analysis.maxHeartRate} bpm",
                                color = MaterialTheme.colorScheme.onBackground,
                                style = MaterialTheme.typography.bodyMedium,
                            )
                            extraSummaries.forEach { summary ->
                                Text(
                                    text = "${summary.label}: " +
                                        "${summary.averageHeartRate} avg · " +
                                        "${summary.minHeartRate}–" +
                                        "${summary.maxHeartRate} bpm",
                                    color = MaterialTheme.colorScheme.onBackground,
                                    style = MaterialTheme.typography.bodyMedium,
                                )
                            }
                        } else {
                            Text(
                                text = "Average: ${analysis.averageHeartRate} bpm",
                                color = MaterialTheme.colorScheme.onBackground,
                                style = MaterialTheme.typography.bodyMedium,
                            )
                        }
                        sweatLossMl?.let { lossMl ->
                            Text(
                                text = "Sweat loss: $lossMl ml",
                                color = MaterialTheme.colorScheme.onBackground,
                                style = MaterialTheme.typography.bodyMedium,
                            )
                        }
                        if (skinTempStartC != null && skinTempMaxC != null) {
                            Text(
                                text = "Skin temp: ${"%.1f".format(skinTempStartC)} → " +
                                    "${"%.1f".format(skinTempMaxC)} °C",
                                color = MaterialTheme.colorScheme.onBackground,
                                style = MaterialTheme.typography.bodyMedium,
                            )
                        }
                        fluidsToReplaceMl?.let { targetMl ->
                            Text(
                                text = "Fluids to replace: $targetMl ml",
                                color = MaterialTheme.colorScheme.onBackground,
                                style = MaterialTheme.typography.bodyMedium,
                            )
                        }
                    }
                    Column(
                        modifier = Modifier.weight(1f),
                        verticalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        if (!showSources) {
                            HeartRateMetricRow(
                                label = "Min",
                                value = "${analysis.minHeartRate} bpm"
                            )
                            HeartRateMetricRow(
                                label = "Max",
                                value = "${analysis.maxHeartRate} bpm"
                            )
                        }
                        caloriesBurned?.let { kcal ->
                            HeartRateMetricRow(label = "Calories", value = kcal.toString())
                        }
                        hrvRmssdMs?.let { hrv ->
                            HeartRateMetricRow(label = "HRV", value = "${hrv.roundToInt()} ms")
                        }
                    }
                }
            },
            content = {
                Column(
                    modifier = Modifier.padding(10.dp),
                    verticalArrangement = Arrangement.spacedBy(Spacing.md),
                ) {
                    analysis.zoneCounts
                        .toList()
                        .asReversed()
                        .forEach { (zone, count) ->
                            val total = analysis.zoneCounts.values.sum().takeIf { it > 0.0 } ?: 1.0
                            val progress = (count / total).toFloat()
                            val zoneRange = zoneBounds[zone]

                            Column(modifier = Modifier.fillMaxWidth()) {
                                Text(
                                    text = "Zone $zone",
                                    color = MaterialTheme.colorScheme.onBackground,
                                    style = MaterialTheme.typography.bodyMedium,
                                )
                                Spacer(Modifier.height(5.dp))
                                Row(modifier = Modifier.fillMaxWidth()) {
                                    Text(
                                        text = if (zone == 0) {
                                            "< ${zoneBounds[1].first} bpm"
                                        } else {
                                            "${zoneRange.first} - ${zoneRange.last} bpm"
                                        },
                                        modifier = Modifier.weight(1f),
                                        color = MaterialTheme.colorScheme.onBackground,
                                        style = MaterialTheme.typography.bodySmall,
                                    )
                                    Spacer(Modifier.weight(1f))
                                    Text(
                                        text = "${(progress * 100).toInt()}% ${formatTime(count.roundToInt())}",
                                        modifier = Modifier.weight(1f),
                                        style = MaterialTheme.typography.bodySmall,
                                        textAlign = TextAlign.End,
                                        color = MaterialTheme.colorScheme.onBackground,
                                    )
                                }
                                Spacer(Modifier.height(5.dp))
                                SimpleProgressIndicator(
                                    progress = progress,
                                    trackColor = MediumDarkGray,
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .height(16.dp)
                                        .clip(MaterialTheme.shapes.large),
                                    progressBarColor = colorsByZone[zone],
                                )
                            }
                        }
                }
            },
        )
    }
}

@Composable
private fun HeartRateSourceLegend(
    labels: List<String>,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 10.dp, vertical = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(Spacing.md),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        labels.forEachIndexed { index, label ->
            HeartRateSourceLegendItem(
                color = HeartRateSourceColors[index % HeartRateSourceColors.size],
                label = label,
            )
        }
    }
}

@Composable
private fun HeartRateSourceLegendItem(
    color: Color,
    label: String,
) {
    Row(
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(8.dp)
                .clip(CircleShape)
                .background(color)
        )
        Text(
            text = label,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onBackground,
        )
    }
}

private val HeartRateSourceColors = listOf(
    Color(0xFFff6700),
    Color(0xFF38BDF8),
    Color(0xFFB388FF),
    Color(0xFF4DD0A0),
)

@Composable
private fun HeartRateMetricRow(
    label: String,
    value: String,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(
            text = "$label:",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onBackground,
        )
        Text(
            text = value,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onBackground,
            textAlign = TextAlign.End,
        )
    }
}
