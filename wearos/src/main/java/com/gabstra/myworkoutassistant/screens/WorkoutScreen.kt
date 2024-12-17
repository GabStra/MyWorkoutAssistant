package com.gabstra.myworkoutassistant.screens

import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.WorkoutState
import com.gabstra.myworkoutassistant.composable.CurrentTime
import com.gabstra.myworkoutassistant.composable.CustomBackHandler
import com.gabstra.myworkoutassistant.composable.HeartRatePolar
import com.gabstra.myworkoutassistant.composable.HeartRateStandard
import com.gabstra.myworkoutassistant.data.SensorDataViewModel
import com.gabstra.myworkoutassistant.data.PolarViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.VibrateGentle
import com.gabstra.myworkoutassistant.composable.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.composable.LifecycleObserver
import com.gabstra.myworkoutassistant.data.cancelWorkoutInProgressNotification
import com.gabstra.myworkoutassistant.data.showWorkoutInProgressNotification
import kotlinx.coroutines.ExperimentalCoroutinesApi

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
    val isRefreshing by viewModel.isRefreshing.collectAsState()

    val triggerMobileNotification by viewModel.enableWorkoutNotificationFlow.collectAsState()

    LaunchedEffect(triggerMobileNotification){
        if(triggerMobileNotification==null) return@LaunchedEffect
        showWorkoutInProgressNotification(context)
    }

    @Composable
    fun heartRateChartComposable(targetZone: Int? = null){
        if(selectedWorkout.usePolarDevice){
            HeartRatePolar(
                modifier = Modifier.fillMaxSize(),
                viewModel,
                polarViewModel,
                userAge,
                targetZone
            )
        }else{
            HeartRateStandard(
                modifier = Modifier.fillMaxSize(),
                viewModel,
                hrViewModel,
                userAge,
                targetZone
            )
        }
    }

    CustomDialogYesOnLongPress(
        show = showWorkoutInProgressDialog,
        title = "Workout in progress",
        handleYesClick = {
            VibrateGentle(context)
            //viewModel.pushAndStoreWorkoutData(false,context)
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
            VibrateGentle(context)
            showWorkoutInProgressDialog = false
            viewModel.resumeWorkout()
        },
        closeTimerInMillis = 2000,
        handleOnAutomaticClose = {
            showWorkoutInProgressDialog = false
            viewModel.resumeWorkout()
        },
        holdTimeInMillis = 1000
    )

    val showSkipDialog by viewModel.isSkipDialogOpen.collectAsState()

    CustomBackHandler(
        onSinglePress = {
            VibrateGentle(context)
            viewModel.openSkipDialog()
            viewModel.lightScreenUp()
        }, onDoublePress = {
            if(workoutState is WorkoutState.Finished || showSkipDialog) return@CustomBackHandler
            showWorkoutInProgressDialog = true
            VibrateGentle(context)
            viewModel.pauseWorkout()
            viewModel.lightScreenUp()
        }
    )

    LifecycleObserver(
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
            .padding(10.dp),
        contentAlignment = Alignment.TopCenter
    ) {
        CurrentTime()
        if(isResuming){
            LoadingScreen(viewModel,"Resuming workout")
            return@Box
        }

        if(isRefreshing){
            LoadingScreen(viewModel,"Reloading workout")
            return@Box
        }

        AnimatedContent(
            targetState = workoutState,
            transitionSpec = {
                fadeIn(animationSpec = tween(500)) togetherWith fadeOut(animationSpec = tween(500))
            }, label = ""
        ) { updatedWorkoutState ->
            when(updatedWorkoutState){
                is WorkoutState.Preparing -> {
                    val state = updatedWorkoutState as WorkoutState.Preparing
                    if(!selectedWorkout.usePolarDevice)
                        PreparingStandardScreen(viewModel,hrViewModel,state)
                    else
                        PreparingPolarScreen(viewModel,navController,polarViewModel,state)
                }
                is WorkoutState.Set -> {
                    val state = updatedWorkoutState as WorkoutState.Set
                    ExerciseScreen(
                        viewModel,
                        state,
                        hearthRateChart = { heartRateChartComposable(state.targetZone) }
                    )
                }
                is WorkoutState.Rest -> {
                    val state = updatedWorkoutState as WorkoutState.Rest
                    RestScreen(
                        viewModel,
                        state,
                        { heartRateChartComposable() },
                        onTimerEnd = {
                            viewModel.storeSetData()
                            viewModel.pushAndStoreWorkoutData(false,context){
                                viewModel.goToNextState()
                            }
                        }
                    )
                }
                is WorkoutState.Finished -> {
                    val state = updatedWorkoutState as WorkoutState.Finished
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
}