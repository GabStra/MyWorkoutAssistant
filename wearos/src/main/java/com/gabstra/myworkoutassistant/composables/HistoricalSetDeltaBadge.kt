package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.runtime.Composable
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme
import com.gabstra.myworkoutassistant.shared.equipments.Equipment
import com.gabstra.myworkoutassistant.shared.setdata.SetData

@Composable
fun HistoricalSetDeltaBadge(
    previousSetData: SetData?,
    currentSetData: SetData?,
    equipment: Equipment?,
    modifier: Modifier = Modifier
) {
    val setDifference by remember(previousSetData, currentSetData, equipment) {
        derivedStateOf { calculateSetDifference(previousSetData, currentSetData, equipment) }
    }
    val differenceText = setDifference.displayText
    val comparison = setDifference.comparison

    if (comparison == SetComparison.EQUAL) return

    val comparisonColor = colorForSetComparisonSummary(comparison)

    Row(
        modifier = modifier.semantics(mergeDescendants = true) {
            contentDescription = differenceText
        },
        horizontalArrangement = Arrangement.spacedBy(5.dp, Alignment.CenterHorizontally),
        verticalAlignment = Alignment.CenterVertically
    ) {
        SetComparisonDeltaIcon(comparison = comparison, iconSize = 16.dp)

        Row(
            horizontalArrangement = Arrangement.spacedBy(4.dp, Alignment.CenterHorizontally),
            verticalAlignment = Alignment.CenterVertically
        ) {
            val lines = setDifference.deltaLines
            if (lines.isEmpty()) {
                ScalableText(
                    text = differenceText,
                    style = MaterialTheme.typography.bodySmall,
                    color = comparisonColor
                )
            } else {
                lines.forEach { line ->
                    ScalableText(
                        text = line.text,
                        style = MaterialTheme.typography.bodySmall,
                        color = colorForSetSegmentTrend(line.trend)
                    )
                }
            }
        }
    }
}
