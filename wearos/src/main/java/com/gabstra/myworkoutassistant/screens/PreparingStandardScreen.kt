package com.gabstra.myworkoutassistant.screens

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import com.gabstra.myworkoutassistant.composables.rememberWearCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.composables.FullScreenLoadingIndicator
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.SensorDataViewModel
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun PreparingStandardScreen(
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    hrViewModel: SensorDataViewModel,
    state: WorkoutState.Preparing,
    onReady: () -> Unit = {}
){
    BackHandler(true) {
        // Do nothing
    }

    val context = LocalContext.current
    val scope = rememberWearCoroutineScope()
    var currentMillis by remember { mutableIntStateOf(0) }

    val hasWorkoutRecord by viewModel.hasWorkoutRecord.collectAsState()
    val isSessionHydrationInFlight by viewModel.isSessionHydrationInFlightFlow.collectAsState()
    val watchHeartRateSamples by hrViewModel.heartRateSampleCount.collectAsState()
    var hasTriggeredNextState by remember { mutableStateOf(false) }
    val watchHeartRateReady = isWatchHeartRateReady(watchHeartRateSamples, currentMillis)

    LaunchedEffect(isSessionHydrationInFlight) {
        if (isSessionHydrationInFlight) {
            return@LaunchedEffect
        }
        currentMillis = 0
        scope.launch {
            while (true) {
                delay(1000)
                currentMillis += 1000
            }
        }
    }
    LaunchedEffect(
        state.dataLoaded,
        hasWorkoutRecord,
        currentMillis,
        isSessionHydrationInFlight,
        watchHeartRateSamples,
    ) {
        if (hasTriggeredNextState || isSessionHydrationInFlight) {
            return@LaunchedEffect
        }

        val isReady = state.dataLoaded && watchHeartRateReady && currentMillis >= 3000

        if (isReady) {
            if (!viewModel.isCurrentPreparingState(state)) {
                hasTriggeredNextState = true
                return@LaunchedEffect
            }
            hasTriggeredNextState = true

            viewModel.lightScreenUp()
            if(hasWorkoutRecord){
                if (viewModel.consumeSkipNextResumeLastState()) {
                    viewModel.finishPreparedResume()
                } else {
                    viewModel.resumeLastState()
                }
            }else{
                viewModel.setWorkoutStart()
            }

            onReady()
        }
    }

    FullScreenLoadingIndicator(
        text = stringResource(
            if (watchHeartRateReady) {
                R.string.wear_getting_workout_ready
            } else {
                R.string.wear_checking_heart_rate
            }
        )
    )
}
