package com.gabstra.myworkoutassistant.composables.workout.pages

import com.gabstra.myworkoutassistant.composables.WearRunningRouteMap

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import androidx.wear.tooling.preview.devices.WearDevices
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.presentation.theme.MyWorkoutAssistantTheme
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.Red
import com.gabstra.myworkoutassistant.shared.running.RunningRoutePoint

/**
 * The route gets its own page because the metrics page could only spare an 88dp strip.
 * The height stays short of the page so the margins remain swipeable: the map consumes
 * horizontal drags for panning.
 */
@Composable
internal fun RunningMapPage(
    route: List<RunningRoutePoint>,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 8.dp, vertical = 4.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(5.dp),
    ) {
        WearRunningRouteMap(
            route = route,
            modifier = Modifier
                .padding(horizontal = 12.dp)
                .height(220.dp),
            backgroundColor = MaterialTheme.colorScheme.surfaceContainerHigh,
            gridColor = MaterialTheme.colorScheme.outline.copy(alpha = 0.45f),
            routeColor = MaterialTheme.colorScheme.primary,
            startColor = Green,
            currentColor = Red,
            labelColor = MaterialTheme.colorScheme.onSurface,
        )
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(stringResource(R.string.run_start_label), style = MaterialTheme.typography.bodyExtraSmall, color = Green)
            Text(stringResource(R.string.run_now_label), style = MaterialTheme.typography.bodyExtraSmall, color = Red)
        }
    }
}

/** Sample track for previews of the map page and of the exercise pager page that hosts it. */
internal val PREVIEW_RUN_ROUTE = listOf(
    RunningRoutePoint(45.4642, 9.1900, 0),
    RunningRoutePoint(45.4648, 9.1912, 30_000),
    RunningRoutePoint(45.4656, 9.1921, 60_000),
    RunningRoutePoint(45.4665, 9.1915, 90_000),
    RunningRoutePoint(45.4671, 9.1902, 120_000),
    RunningRoutePoint(45.4667, 9.1889, 150_000),
)

@Preview(device = WearDevices.LARGE_ROUND, showBackground = true)
@Composable
private fun RunningMapPagePreview() {
    MyWorkoutAssistantTheme {
        RunningMapPage(route = PREVIEW_RUN_ROUTE, modifier = Modifier.fillMaxSize())
    }
}
