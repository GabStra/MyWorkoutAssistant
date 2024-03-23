package com.gabstra.myworkoutassistant.composable

import android.util.Log
import android.widget.Toast
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.health.services.client.data.ExerciseState
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.MeasureDataViewModel
import com.gabstra.myworkoutassistant.data.PolarViewModel
import com.gabstra.myworkoutassistant.data.UiState
import com.gabstra.myworkoutassistant.data.VibrateShortImpulse
import com.gabstra.myworkoutassistant.shared.getMaxHearthRatePercentage
import com.gabstra.myworkoutassistant.shared.mapPercentage
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import com.google.android.horologist.composables.ProgressIndicatorSegment
import com.google.android.horologist.composables.SegmentedProgressIndicator
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive

private fun getProgressIndicatorSegments() = listOf(
    ProgressIndicatorSegment(.166f, Color.hsl(0f, 0.02f, 0.68f)),
    ProgressIndicatorSegment(.166f, Color.hsl(208f, 0.61f, 0.76f)),
    ProgressIndicatorSegment(.166f, Color.hsl(200f, 0.66f, 0.49f)),
    ProgressIndicatorSegment(.166f, Color.hsl(113f, 0.79f, 0.34f)),
    ProgressIndicatorSegment(.166f, Color.hsl(27f, 0.97f, 0.54f)),
    ProgressIndicatorSegment(.166f, Color.hsl(9f, 0.88f, 0.45f)),
)

@Composable
fun HeartRateCircularChart(
    modifier: Modifier = Modifier,
    appViewModel: AppViewModel,
    hr: Int,
    age: Int = 28
) {
    val context = LocalContext.current
    val mhrPercentage = remember(hr, age) { getMaxHearthRatePercentage(hr, age) }

    val isDataStale = remember { mutableStateOf(false) }

    // Simplified data stale counter using LaunchedEffect for automatic cancellation
    LaunchedEffect(hr) {
        if (hr > 0) {
            isDataStale.value = false
            delay(5000)  // wait for 5 seconds
            isDataStale.value = true
        }
    }

    // Collect the heart rate value from the StateFlow and call registerHeartBeat at 500 ms intervals
    // Simplified version without explicitly using a ticker channel
    LaunchedEffect(hr) {
        while (isActive) {
            appViewModel.registerHeartBeat(hr)
            delay(500)
        }
    }

    // Handle heart rate over limit scenario
    if (mhrPercentage > 100) {
        SideEffect {
            Toast.makeText(context, "Heart rate over limit", Toast.LENGTH_SHORT).show()
            VibrateShortImpulse(context)
        }
    }

    val mapPercentage = remember(mhrPercentage) { mapPercentage(mhrPercentage) }
    val segments = remember { getProgressIndicatorSegments() }

    HeartRateView(modifier, hr, isDataStale.value, mapPercentage, segments)
}

@OptIn(ExperimentalHorologistApi::class)
@Composable
private fun HeartRateView(
    modifier: Modifier,
    hr: Int,
    isDataStale: Boolean,
    mapPercentage: Float,
    segments: List<ProgressIndicatorSegment>
) {
    Box(
        modifier = modifier,
        contentAlignment = Alignment.BottomCenter
    ) {
        // Heart rate display logic
        Row(
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically
        ) {
            if (hr != 0) PulsingHeartWithBpm(hr) else HeartIcon(modifier = Modifier.size(12.dp))
            Spacer(modifier = Modifier.width(8.dp))
            Text(
                text = if (hr == 0) "-" else hr.toString(),
                style = MaterialTheme.typography.caption2,
                color = if (isDataStale) Color.Gray else Color.White
            )
        }

        // Progress indicator logic
        SegmentedProgressIndicator(
            trackSegments = segments,
            progress = mapPercentage,
            modifier = Modifier.fillMaxSize(),
            strokeWidth = 4.dp,
            paddingAngle = 2f,
            startAngle = 110f,
            endAngle = 250f,
            trackColor = Color.DarkGray,
        )
    }
}


@Composable
fun HeartRateStandard(
    modifier: Modifier = Modifier,
    appViewModel: AppViewModel,
    hrViewModel: MeasureDataViewModel,
    userAge : Int
) {
    val uiState by hrViewModel.uiState.collectAsState()

    val currentHeartRate by hrViewModel.heartRateBpm.collectAsState()

    var lastNonZeroHeartRate by remember { mutableIntStateOf(0) }

    LaunchedEffect(currentHeartRate){
        if(currentHeartRate > 0){
            lastNonZeroHeartRate = currentHeartRate.toInt()
        }
    }

    val hr = if (uiState is UiState.HeartRateAvailable) lastNonZeroHeartRate else 0

    HeartRateCircularChart(modifier = modifier,appViewModel, hr = hr, age = userAge)
}

@Composable
fun HeartRatePolar(
    modifier: Modifier = Modifier,
    appViewModel: AppViewModel,
    polarViewModel: PolarViewModel,
    userAge : Int
) {
    val hrData by polarViewModel.hrDataState.collectAsState()
    val hr = hrData ?: 0
    HeartRateCircularChart(modifier = modifier,appViewModel, hr = hr, age = userAge)
}