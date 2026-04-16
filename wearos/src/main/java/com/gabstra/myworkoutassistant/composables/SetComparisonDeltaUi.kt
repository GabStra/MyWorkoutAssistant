package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.DragHandle
import androidx.compose.material.icons.filled.SwapVert
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.Icon
import androidx.wear.compose.material3.MaterialTheme
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.Red

@Composable
fun colorForSetComparisonSummary(comparison: SetComparison): Color = when (comparison) {
    SetComparison.BETTER -> Green
    SetComparison.WORSE -> Red
    SetComparison.EQUAL -> MaterialTheme.colorScheme.onBackground
    SetComparison.MIXED -> MaterialTheme.colorScheme.tertiary
}

@Composable
fun colorForSetSegmentTrend(trend: SetSegmentTrend?): Color = when (trend) {
    SetSegmentTrend.BETTER -> Green
    SetSegmentTrend.WORSE -> Red
    SetSegmentTrend.EQUAL -> MaterialTheme.colorScheme.onBackground
    null -> MaterialTheme.colorScheme.tertiary
}

@Composable
fun SetComparisonDeltaIcon(
    comparison: SetComparison,
    modifier: Modifier = Modifier,
    iconSize: Dp = 20.dp,
) {
    when (comparison) {
        SetComparison.EQUAL -> Icon(
            imageVector = Icons.Filled.DragHandle,
            contentDescription = null,
            modifier = modifier.size(iconSize),
            tint = MaterialTheme.colorScheme.onBackground,
        )
        SetComparison.BETTER -> Icon(
            imageVector = Icons.Filled.ArrowUpward,
            contentDescription = null,
            modifier = modifier.size(iconSize),
            tint = Green,
        )
        SetComparison.WORSE -> Icon(
            imageVector = Icons.Filled.ArrowDownward,
            contentDescription = null,
            modifier = modifier.size(iconSize),
            tint = Red,
        )
        SetComparison.MIXED -> Icon(
            imageVector = Icons.Filled.SwapVert,
            contentDescription = null,
            modifier = modifier.size(iconSize),
            tint = MaterialTheme.colorScheme.tertiary,
        )
    }
}
