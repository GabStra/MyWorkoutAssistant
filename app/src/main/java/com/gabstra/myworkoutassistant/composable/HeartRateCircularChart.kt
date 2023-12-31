package com.gabstra.myworkoutassistant.composable

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
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.health.services.client.data.ExerciseState
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.getMaxHearthRatePercentage
import com.gabstra.myworkoutassistant.data.MeasureDataViewModel
import com.gabstra.myworkoutassistant.data.VibrateShortImpulse
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import com.google.android.horologist.composables.ProgressIndicatorSegment
import com.google.android.horologist.composables.SegmentedProgressIndicator

@OptIn(ExperimentalHorologistApi::class)
@Composable
fun HeartRateCircularChart(
    modifier: Modifier = Modifier.fillMaxSize(),
    hrViewModel: MeasureDataViewModel
){
    val uiState by hrViewModel.exerciseServiceState.collectAsState();
    val hr= remember(uiState.exerciseState,uiState.exerciseMetrics.heartRate) {
        if(uiState.exerciseState == ExerciseState.ACTIVE) uiState.exerciseMetrics.heartRate ?: 0 else 0
    }

    val context = LocalContext.current
    val mhrPercentage =  remember(hr) { getMaxHearthRatePercentage(hr.toFloat(),28) }

    LaunchedEffect(mhrPercentage){
        if(mhrPercentage > 100){
            Toast.makeText(context, "Heart rate over limit", Toast.LENGTH_SHORT).show()
            VibrateShortImpulse(context);
        }
    }

    val mapPercentage = remember(mhrPercentage){ mapPercentage(mhrPercentage) }

    val bpm = remember(hr) {
        hr.toInt()
    }

    val segments = listOf(
        ProgressIndicatorSegment(.166f, Color.hsl(0f,0.02f,0.68f)),
        ProgressIndicatorSegment(.166f, Color.hsl(208f,0.61f,0.76f)),
        ProgressIndicatorSegment(.166f, Color.hsl(200f,0.66f,0.49f)),
        ProgressIndicatorSegment(.166f, Color.hsl(113f,0.79f,0.34f)),
        ProgressIndicatorSegment(.166f, Color.hsl(27f,0.97f,0.54f)),
        ProgressIndicatorSegment(.166f, Color.hsl(9f,0.88f,0.45f)),
    )

    Box(
        modifier = modifier,
        contentAlignment = Alignment.BottomCenter
    ){
        Row(
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically
        ){
            if(bpm != 0)
                PulsingHeartWithBpm(bpm)
            else
                HeartIcon(modifier = Modifier.size(12.dp))
            Spacer(modifier= Modifier.width(8.dp))
            Text(
                text="${if(bpm==0) "-" else bpm}",
                style = MaterialTheme.typography.caption2
            )
        }

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

private fun mapPercentage(percentage: Float): Float {
    return if (percentage <= 50) {
        percentage * 0.00332f
    } else {
        0.166f + ((percentage - 50) / 10) * 0.166f
    }
}

fun mapPercentageToZone(percentage: Float): Int {
    val mappedValue = if (percentage <= 50) {
        percentage * 0.00332f
    } else {
        0.166f + ((percentage - 50) / 10) * 0.166f
    }

    return (mappedValue / 0.166f).toInt()
}