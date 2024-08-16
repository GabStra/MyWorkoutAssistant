package com.gabstra.myworkoutassistant.screens

import android.util.Log
import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.Crossfade
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.LifecycleOwner
import androidx.navigation.NavController
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.WorkoutState
import com.gabstra.myworkoutassistant.composable.CurrentTime
import com.gabstra.myworkoutassistant.composable.CustomDialog
import com.gabstra.myworkoutassistant.composable.HeartRatePolar
import com.gabstra.myworkoutassistant.composable.HeartRateStandard
import com.gabstra.myworkoutassistant.data.SensorDataViewModel
import com.gabstra.myworkoutassistant.data.PolarViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.VibrateOnce
import com.gabstra.myworkoutassistant.data.findActivity
import com.gabstra.myworkoutassistant.composable.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.composable.KeepOn
import com.gabstra.myworkoutassistant.data.VibrateTwice
import com.gabstra.myworkoutassistant.data.cancelWorkoutInProgressNotification
import com.gabstra.myworkoutassistant.data.showWorkoutInProgressNotification
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@Composable
fun LifecycleObserver(
    onStarted: () -> Unit = {},
    onPaused: () -> Unit = {},
    onStopped: () -> Unit = {},
    onResumed: () -> Unit = {}
) {
    val context = LocalContext.current
    val activity = context.findActivity()
    val lifecycleOwner = activity as LifecycleOwner
    val onStartedState = rememberUpdatedState(onStarted)
    val onPausedState = rememberUpdatedState(onPaused)
    val onStoppedState = rememberUpdatedState(onStopped)
    val onResumedState = rememberUpdatedState(onResumed)

    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_START -> onStartedState.value()
                Lifecycle.Event.ON_PAUSE -> onPausedState.value()
                Lifecycle.Event.ON_STOP -> onStoppedState.value()
                Lifecycle.Event.ON_RESUME -> onResumedState.value()
                else -> Unit
            }
        }

        lifecycleOwner.lifecycle.addObserver(observer)

        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
        }
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
@Composable
fun WorkoutScreen(
    navController: NavController,
    viewModel : AppViewModel,
    hrViewModel: SensorDataViewModel,
    polarViewModel: PolarViewModel
){
    var showWorkoutInProgressDialog by remember { mutableStateOf(false) }
    val context = LocalContext.current
    val workoutState by viewModel.workoutState.collectAsState()
    val selectedWorkout by viewModel.selectedWorkout
    val userAge by viewModel.userAge
    val hasPolarApiBeenInitialized by polarViewModel.hasBeenInitialized.collectAsState()
    val isResuming by viewModel.isResuming.collectAsState()


    val heartRateChartComposable =  @Composable {
        if(selectedWorkout.usePolarDevice){
            HeartRatePolar(
                modifier = Modifier.fillMaxSize(),
                viewModel,
                polarViewModel,
                userAge
            )
        }else{
            HeartRateStandard(
                modifier = Modifier.fillMaxSize(),
                viewModel,
                hrViewModel,
                userAge
            )
        }
    }

    BackHandler(true) {
        if(workoutState is WorkoutState.Finished) return@BackHandler
        showWorkoutInProgressDialog = true
        viewModel.pauseWorkout()
    }

    CustomDialogYesOnLongPress(
        show = showWorkoutInProgressDialog,
        title = "Workout in progress",
        handleYesClick = {
            VibrateOnce(context)
            viewModel.pushAndStoreWorkoutData(false,context)
            if(!selectedWorkout.usePolarDevice){
                hrViewModel.stopMeasuringHeartRate()
            }else{
                polarViewModel.disconnectFromDevice()
            }
            cancelWorkoutInProgressNotification(context)
            navController.navigate(Screen.WorkoutSelection.route){
                popUpTo(Screen.WorkoutSelection.route) {
                    inclusive = true
                }
            }
            showWorkoutInProgressDialog = false
        },
        handleNoClick = {
            VibrateOnce(context)
            showWorkoutInProgressDialog = false
            viewModel.resumeWorkout()
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            showWorkoutInProgressDialog = false
            viewModel.resumeWorkout()
        },
        holdTimeInMillis = 1000
    )

    LifecycleObserver(
        onStarted = {

        },
        onPaused = {
            if(!selectedWorkout.usePolarDevice){
                hrViewModel.stopMeasuringHeartRate()
            }
        },
        onResumed = {
            if(!selectedWorkout.usePolarDevice){
                hrViewModel.startMeasuringHeartRate()
            }
            else if(hasPolarApiBeenInitialized){
                polarViewModel.connectToDevice()
            }
        }
    )

    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(5.dp),
        contentAlignment = Alignment.TopCenter
    ) {
        CurrentTime()
        if(isResuming){
            LoadingScreen("Resuming workout")
        }else{
            when(workoutState){
                is WorkoutState.Preparing -> {
                    val state = workoutState as WorkoutState.Preparing
                    if(!selectedWorkout.usePolarDevice)
                        PreparingStandardScreen(viewModel,hrViewModel,state,onReady = {
                            showWorkoutInProgressNotification(context)
                        })
                    else
                        PreparingPolarScreen(viewModel,navController,polarViewModel,state,onReady = {
                            showWorkoutInProgressNotification(context)
                        })
                }
                is WorkoutState.Set -> {
                    val state = workoutState as WorkoutState.Set
                    ExerciseScreen(
                        viewModel,
                        state,
                        heartRateChartComposable
                    )
                }
                is WorkoutState.Rest -> {
                    val state = workoutState as WorkoutState.Rest
                    RestScreen(
                        viewModel,
                        state,
                        heartRateChartComposable)
                }
                is WorkoutState.Finished -> {
                    val state = workoutState as WorkoutState.Finished
                    WorkoutCompleteScreen(
                        navController,
                        viewModel,
                        state,
                        hrViewModel,
                        polarViewModel
                    )
                }
            }
        }
    }

    KeepOn()
}