package com.gabstra.myworkoutassistant.screens

import android.util.Log
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.health.services.client.data.ExerciseState
import com.gabstra.myhomeworkoutassistant.data.AppViewModel
import com.gabstra.myhomeworkoutassistant.data.WorkoutState
import com.gabstra.myworkoutassistant.composable.LoadingText
import com.gabstra.myworkoutassistant.data.MeasureDataViewModel
import com.gabstra.myworkoutassistant.data.VibrateOnce
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@Composable
fun PreparingScreen(
    viewModel: AppViewModel,
    hrViewModel: MeasureDataViewModel,
    state: WorkoutState.Preparing,
){
    val uiState by hrViewModel.exerciseServiceState.collectAsState()

    val heartRate = remember(uiState) {
        uiState.exerciseMetrics.heartRate?.toInt() ?: 0
    }

    val scope = rememberCoroutineScope()
    var currentMillis by remember { mutableIntStateOf(0) }

    LaunchedEffect(Unit){
        scope.launch {
            while (true) {
                delay(1000) // Update every sec.
                currentMillis += 1000
            }
        }
    }

    LaunchedEffect(uiState.exerciseState, heartRate,state,currentMillis) {
        val isReady = (uiState.exerciseState == ExerciseState.ACTIVE) && (heartRate > 0) && state.dataLoaded && currentMillis >=2000
        if (isReady) {
            viewModel.goToNextState()
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 40.dp),
        contentAlignment = Alignment.Center
    ) {
        Row(modifier = Modifier.width(75.dp)){
            LoadingText(baseText = "Loading")
        }

    }
}