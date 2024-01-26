package com.gabstra.myworkoutassistant.screens

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.Crossfade
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
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
import androidx.compose.ui.platform.LocalContext
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
import com.gabstra.myworkoutassistant.data.MeasureDataViewModel
import com.gabstra.myworkoutassistant.data.PolarViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.VibrateOnce
import com.gabstra.myworkoutassistant.data.findActivity
import com.gabstra.myworkoutassistant.KeepScreenOn
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

@Composable
fun WorkoutScreen(
    navController: NavController,
    viewModel : AppViewModel,
    hrViewModel: MeasureDataViewModel,
    polarViewModel: PolarViewModel
){
    var showWorkoutInProgressDialog by remember { mutableStateOf(false) }
    val context = LocalContext.current
    var screenLocked by remember { mutableStateOf(false) }
    val workoutState by viewModel.workoutState.collectAsState()
    val selectedWorkout by viewModel.selectedWorkout
    val userAge by viewModel.userAge
    val hasPolarApiBeenInitialized by polarViewModel.hasBeenInitialized.collectAsState()

    BackHandler(true) {
        if(!screenLocked) showWorkoutInProgressDialog=true
    }
    val coroutineScope = rememberCoroutineScope()

    CustomDialog(
        show = showWorkoutInProgressDialog,
        title = "Workout in progress",
        handleYesClick = {
            VibrateOnce(context)
            showWorkoutInProgressDialog=false
            if(!selectedWorkout.usePolarDevice){
                hrViewModel.endExercise()
            }else{
                polarViewModel.disconnectFromDevice()
            }
            coroutineScope.launch {
                navController.navigate(Screen.WorkoutSelection.route){
                    popUpTo(Screen.WorkoutSelection.route) {
                        inclusive = true
                    }
                }
            }
        },
        handleNoClick = {
            VibrateOnce(context)
            showWorkoutInProgressDialog = false
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            showWorkoutInProgressDialog = false
        }
    )

    LifecycleObserver(
        onPaused = {
            if(!selectedWorkout.usePolarDevice){
                hrViewModel.endExercise()
            }
        },
        onResumed = {
            if(!selectedWorkout.usePolarDevice){
                hrViewModel.startExercise()
            }
            else{
                if(hasPolarApiBeenInitialized){
                    polarViewModel.connectToDevice()
                }
            }
        }
    )

    KeepScreenOn()

    Box(
        contentAlignment = Alignment.TopCenter
    ) {
        CurrentTime()
        when(workoutState){
            is WorkoutState.Preparing -> {
                val state = workoutState as WorkoutState.Preparing
                if(!selectedWorkout.usePolarDevice)
                    PreparingStandardScreen(viewModel,hrViewModel,state)
                else
                    PreparingPolarScreen(viewModel,navController,polarViewModel,state)
            }
            is WorkoutState.Set -> {
                val state = workoutState as WorkoutState.Set
                ExerciseScreen(
                    viewModel,
                    state,
                    onScreenLocked = {
                        screenLocked=true
                    },
                    onScreenUnlocked = {
                        screenLocked=false
                    },
                    hearthRateChart = {
                        if(!selectedWorkout.usePolarDevice)
                            HeartRateStandard(
                                modifier = Modifier.fillMaxSize(),
                                hrViewModel,
                                userAge
                            )
                        else
                            HeartRatePolar(
                                modifier = Modifier.fillMaxSize(),
                                polarViewModel,
                                userAge
                            )
                    }
                )
            }
            is WorkoutState.Rest -> {
                val state = workoutState as WorkoutState.Rest
                RestScreen(viewModel,state)
            }
            is WorkoutState.Finished -> {
                val state = workoutState as WorkoutState.Finished
                WorkoutCompleteScreen(navController, viewModel,state)
            }
        }
    }

}