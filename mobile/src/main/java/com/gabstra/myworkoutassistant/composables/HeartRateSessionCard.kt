package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
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

@Composable
fun HeartRateSessionCard(
    title: String,
    analysis: HeartRateSessionAnalysis,
    userAge: Int,
    measuredMaxHeartRate: Int? = null,
    restingHeartRate: Int? = null,
    modifier: Modifier = Modifier,
    caloriesBurned: Int? = null,
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
                HeartRateChartContent(
                    modifier = Modifier.fillMaxWidth(),
                    cartesianChartModel = analysis.chartModel,
                    userAge = userAge,
                    measuredMaxHeartRate = measuredMaxHeartRate,
                    restingHeartRate = restingHeartRate,
                    minYBpm = analysis.minChartY,
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
                        Text(
                            text = "Average: ${analysis.averageHeartRate} bpm",
                            color = MaterialTheme.colorScheme.onBackground,
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    }
                    Column(
                        modifier = Modifier.weight(1f),
                        verticalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        HeartRateMetricRow(label = "Min", value = "${analysis.minHeartRate} bpm")
                        HeartRateMetricRow(label = "Max", value = "${analysis.maxHeartRate} bpm")
                        caloriesBurned?.let { kcal ->
                            HeartRateMetricRow(label = "Calories", value = kcal.toString())
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
                            val total = analysis.zoneCounts.values.sum().takeIf { it > 0 } ?: 1
                            val progress = count.toFloat() / total
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
                                        text = "${(progress * 100).toInt()}% ${formatTime(count)}",
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
