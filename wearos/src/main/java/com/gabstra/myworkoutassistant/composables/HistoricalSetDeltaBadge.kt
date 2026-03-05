package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.Icon
import androidx.wear.compose.material3.MaterialTheme
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.Red
import com.gabstra.myworkoutassistant.shared.equipments.Equipment
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.DragHandle
import androidx.compose.material.icons.filled.SwapVert
import androidx.compose.runtime.derivedStateOf
import androidx.compose.ui.text.style.TextAlign

@Composable
fun HistoricalSetDeltaBadge(
    previousSetData: SetData?,
    currentSetData: SetData?,
    equipment: Equipment?,
    modifier: Modifier = Modifier
) {
    val comparison by remember(previousSetData, currentSetData) {
        derivedStateOf { compareSets(previousSetData, currentSetData) }
    }
    val differenceText by remember(previousSetData, currentSetData, equipment) {
        derivedStateOf { calculateSetDifference(previousSetData, currentSetData, equipment) }
    }
    val comparisonColor = when (comparison) {
        SetComparison.BETTER -> Green
        SetComparison.WORSE -> Red
        SetComparison.EQUAL -> MaterialTheme.colorScheme.onBackground
        SetComparison.MIXED -> MaterialTheme.colorScheme.tertiary
    }

    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(4.dp, Alignment.CenterHorizontally),
        verticalAlignment = Alignment.CenterVertically
    ) {
        when (comparison) {
            SetComparison.EQUAL -> {
                Icon(
                    imageVector = Icons.Filled.DragHandle,
                    contentDescription = null,
                    modifier = Modifier.size(16.dp),
                    tint = MaterialTheme.colorScheme.onBackground
                )
            }

            SetComparison.BETTER -> {
                Icon(
                    imageVector = Icons.Filled.ArrowUpward,
                    contentDescription = null,
                    modifier = Modifier.size(16.dp),
                    tint = Green
                )
            }

            SetComparison.WORSE -> {
                Icon(
                    imageVector = Icons.Filled.ArrowDownward,
                    contentDescription = null,
                    modifier = Modifier.size(16.dp),
                    tint = Red
                )
            }

            SetComparison.MIXED -> {
                Icon(
                    imageVector = Icons.Filled.SwapVert,
                    contentDescription = null,
                    modifier = Modifier.size(16.dp),
                    tint = MaterialTheme.colorScheme.tertiary
                )
            }
        }

        ScalableText(
            text = differenceText,
            style = MaterialTheme.typography.bodySmall,
            textAlign = TextAlign.Center,
            color = comparisonColor
        )
    }
}
