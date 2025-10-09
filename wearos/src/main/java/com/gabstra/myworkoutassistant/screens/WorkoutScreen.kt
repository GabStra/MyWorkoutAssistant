package com.gabstra.myworkoutassistant.screens

import android.content.Context
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
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
import androidx.core.content.edit
import androidx.navigation.NavController
import com.gabstra.myworkoutassistant.composables.CustomBackHandler
import com.gabstra.myworkoutassistant.composables.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.composables.HeartRatePolar
import com.gabstra.myworkoutassistant.composables.HeartRateStandard
import com.gabstra.myworkoutassistant.composables.LifecycleObserver
import com.gabstra.myworkoutassistant.composables.WorkoutStateHeader
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.PolarViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.SensorDataViewModel
import com.gabstra.myworkoutassistant.data.cancelWorkoutInProgressNotification
import com.gabstra.myworkoutassistant.data.showWorkoutInProgressNotification
import com.gabstra.myworkoutassistant.notifications.WorkoutNotificationHelper
import com.gabstra.myworkoutassistant.shared.viewmodels.HeartRateChangeViewModel
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import kotlinx.coroutines.ExperimentalCoroutinesApi

@OptIn(ExperimentalCoroutinesApi::class)
@Composable
fun WorkoutScreen(
    navController: NavController,
    viewModel : AppViewModel,
    hapticsViewModel: HapticsViewModel,
    heartRateChangeViewModel : HeartRateChangeViewModel,
    hrViewModel: SensorDataViewModel,
    polarViewModel: PolarViewModel,
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
        val notificationHelper = WorkoutNotificationHelper(context)
        notificationHelper.clearChannelNotifications()
        showWorkoutInProgressNotification(context)
    }

    @Composable
    fun heartRateChartComposable(
        lowerBoundMaxHRPercent: Float? = null,
        upperBoundMaxHRPercent: Float? = null
    ){
        if(selectedWorkout.usePolarDevice){
            HeartRatePolar(
                modifier = Modifier.fillMaxSize(),
                viewModel,
                hapticsViewModel,
                heartRateChangeViewModel,
                polarViewModel,
                userAge,
                lowerBoundMaxHRPercent,
                upperBoundMaxHRPercent
            )
        }else{
            HeartRateStandard(
                modifier = Modifier.fillMaxSize(),
                viewModel,
                hapticsViewModel,
                heartRateChangeViewModel,
                hrViewModel,
                userAge,
                lowerBoundMaxHRPercent,
                upperBoundMaxHRPercent
            )
        }
    }

    CustomDialogYesOnLongPress(
        show = showWorkoutInProgressDialog,
        title = "Workout in progress",
        handleYesClick = {
            hapticsViewModel.doGentleVibration()

            val prefs = context.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
            prefs.edit { putBoolean("isWorkoutInProgress", false) }

            //viewModel.pushAndStoreWorkoutData(false,context)
            if(!selectedWorkout.usePolarDevice){
                hrViewModel.stopMeasuringHeartRate()
            }else{
                polarViewModel.disconnectFromDevice()
            }
            cancelWorkoutInProgressNotification(context)
            navController.navigate(Screen.WorkoutSelection.route){
                popUpTo(0) {
                    inclusive = true
                }
            }
            showWorkoutInProgressDialog = false
        },
        handleNoClick = {
            hapticsViewModel.doGentleVibration()
            showWorkoutInProgressDialog = false
            viewModel.resumeWorkout()
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            showWorkoutInProgressDialog = false
            viewModel.resumeWorkout()
        },
        holdTimeInMillis = 1000,
        onVisibilityChange = { isVisible ->
            if (isVisible) {
                viewModel.setDimming(false)
            } else {
                viewModel.reEvaluateDimmingForCurrentState()
            }
        }
    )

    val isCustomDialogOpen by viewModel.isCustomDialogOpen.collectAsState()

    CustomBackHandler(
        onPress = {
            hapticsViewModel.doGentleVibration()
        },
        onSinglePress = {
            if(showWorkoutInProgressDialog) return@CustomBackHandler
            viewModel.openCustomDialog()
            viewModel.lightScreenUp()
        },
        onDoublePress = {
            if(workoutState is WorkoutState.Completed || isCustomDialogOpen) return@CustomBackHandler
            showWorkoutInProgressDialog = true
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
            .fillMaxSize(),
    ) {
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
            }, label = "",
            contentAlignment = Alignment.TopCenter
        ) { updatedWorkoutState ->
            WorkoutStateHeader(updatedWorkoutState,viewModel,hapticsViewModel)

            when(updatedWorkoutState){
                is WorkoutState.Preparing -> {
                    val state = updatedWorkoutState
                    if(!selectedWorkout.usePolarDevice)
                        PreparingStandardScreen(viewModel,hapticsViewModel,hrViewModel,state)
                    else
                        PreparingPolarScreen(viewModel,hapticsViewModel,navController,polarViewModel,state)
                }
                is WorkoutState.Set -> {
                    val state = updatedWorkoutState
                    LaunchedEffect(state) {
                        heartRateChangeViewModel.reset()
                    }

                    ExerciseScreen(
                        viewModel,
                        hapticsViewModel,
                        state,
                        hearthRateChart = {
                            heartRateChartComposable(state.lowerBoundMaxHRPercent,state.upperBoundMaxHRPercent)
                        }
                    )
                }
                is WorkoutState.Rest -> {
                    val state = updatedWorkoutState
                    LaunchedEffect(state) {
                        heartRateChangeViewModel.reset()
                    }

                    RestScreen(
                        viewModel,
                        hapticsViewModel,
                        state,
                        { heartRateChartComposable() },
                        onTimerEnd = {
                            viewModel.storeSetData()
                            viewModel.pushAndStoreWorkoutData(false,context){
                                viewModel.goToNextState()
                                viewModel.lightScreenUp()
                            }
                        }
                    )
                }
                is WorkoutState.Completed -> {
                    val state = updatedWorkoutState
                    WorkoutCompleteScreen(
                        navController,
                        viewModel,
                        state,
                        hrViewModel,
                        hapticsViewModel,
                        polarViewModel
                    )
                }
            }
        }
    }
}