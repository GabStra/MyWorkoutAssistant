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
import androidx.compose.runtime.key
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
import com.gabstra.myworkoutassistant.composables.TutorialOverlay
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
    showHeartRateTutorial: Boolean,
    onDismissHeartRateTutorial: () -> Unit,
    showSetScreenTutorial: Boolean,
    onDismissSetScreenTutorial: () -> Unit,
    showRestScreenTutorial: Boolean,
    onDismissRestScreenTutorial: () -> Unit,
){
    var showWorkoutInProgressDialog by remember { mutableStateOf(false) }
    val context = LocalContext.current
    val screenState by viewModel.screenState.collectAsState()
    val workoutState = screenState.workoutState
    val selectedWorkout = screenState.selectedWorkout
    val userAge = screenState.userAge
    val hasPolarApiBeenInitialized by polarViewModel.hasBeenInitialized.collectAsState()
    val isResuming = screenState.isResuming
    val isRefreshing = screenState.isRefreshing

    val triggerMobileNotification = screenState.enableWorkoutNotificationFlow

    LaunchedEffect(triggerMobileNotification){
        if(triggerMobileNotification==null) return@LaunchedEffect
        try {
            val notificationHelper = WorkoutNotificationHelper(context)
            notificationHelper.clearChannelNotifications()
            showWorkoutInProgressNotification(context)
        } catch (exception: Exception) {
            android.util.Log.e("WorkoutScreen", "Error showing workout notification", exception)
        }
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
            try {
                if(!selectedWorkout.usePolarDevice){
                    hrViewModel.stopMeasuringHeartRate()
                }else{
                    polarViewModel.disconnectFromDevice()
                }
            } catch (exception: Exception) {
                android.util.Log.e("WorkoutScreen", "Error stopping sensors on workout end", exception)
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
        onVisibilityChange = { isVisible ->
            if (isVisible) {
                viewModel.setDimming(false)
            } else {
                viewModel.reEvaluateDimmingForCurrentState()
            }
        }
    )

    val isCustomDialogOpen = screenState.isCustomDialogOpen

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
            try {
                if(!selectedWorkout.usePolarDevice){
                    hrViewModel.stopMeasuringHeartRate()
                }
            } catch (exception: Exception) {
                android.util.Log.e("WorkoutScreen", "Error stopping heart rate measurement", exception)
            }
        },
        onResumed = {
            try {
                if(!selectedWorkout.usePolarDevice){
                    hrViewModel.startMeasuringHeartRate()
                }
                else if(hasPolarApiBeenInitialized){
                    polarViewModel.foregroundEntered()
                    polarViewModel.connectToDevice()
                }
            } catch (exception: Exception) {
                android.util.Log.e("WorkoutScreen", "Error resuming sensor/Polar device", exception)
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

        if (showHeartRateTutorial) {
            TutorialOverlay(
                visible = true,
                text = "Heart rate (left)\nTap the number to change how it's shown.\n\nWorkout progress (right)\nShows where you are in the workout.\n\nBack button\nUse presses to pause or end.",
                onDismiss = onDismissHeartRateTutorial,
                hapticsViewModel = hapticsViewModel
            )
        } else {
            val stateTypeKey = remember(workoutState) {
                when (workoutState) {
                    is WorkoutState.Preparing -> "Preparing"
                    is WorkoutState.Set -> "Set"
                    is WorkoutState.Rest -> "Rest"
                    is WorkoutState.Completed -> "Completed"
                }
            }

            @Suppress("UnusedContentLambdaTargetStateParameter")
            AnimatedContent(
                targetState = stateTypeKey,
                transitionSpec = {
                    fadeIn(animationSpec = tween(500)) togetherWith fadeOut(animationSpec = tween(500))
                }, label = "",
                contentAlignment = Alignment.TopCenter
            ) { _ ->
                // Note: We use workoutState directly (which changes when stateTypeKey changes) instead of the lambda parameter
                // The content correctly uses workoutState which changes when stateTypeKey changes
                WorkoutStateHeader(workoutState,viewModel,hapticsViewModel)

                when(workoutState){
                    is WorkoutState.Preparing -> {
                        val state = workoutState as WorkoutState.Preparing
                        if(!selectedWorkout.usePolarDevice)
                            PreparingStandardScreen(viewModel,hapticsViewModel,hrViewModel,state)
                        else
                            PreparingPolarScreen(viewModel,hapticsViewModel,navController,polarViewModel,state)
                    }
                    is WorkoutState.Set -> {
                        val state = workoutState as WorkoutState.Set
                        LaunchedEffect(state) {
                            try {
                                heartRateChangeViewModel.reset()
                            } catch (exception: Exception) {
                                android.util.Log.e("WorkoutScreen", "Error resetting heart rate change view model", exception)
                            }
                        }

                        if (showSetScreenTutorial) {
                            TutorialOverlay(
                                visible = true,
                                text = "Move between pages\nSwipe left or right.\n\nScroll long text\nTap the exercise title or header.\n\nReturn to details\nScreen goes back after 10 seconds.\n\nFinish the set\nUse Complete Set or back button.",
                                onDismiss = onDismissSetScreenTutorial,
                                hapticsViewModel = hapticsViewModel
                            )
                        } else {
                            key(state.exerciseId) {
                                ExerciseScreen(
                                    viewModel = viewModel,
                                    hapticsViewModel = hapticsViewModel,
                                    state = state,
                                    hearthRateChart = {
                                        heartRateChartComposable(state.lowerBoundMaxHRPercent,state.upperBoundMaxHRPercent)
                                    },
                                    navController = navController,
                                )
                            }
                        }
                    }
                    is WorkoutState.Rest -> {
                        val state = workoutState as WorkoutState.Rest
                        LaunchedEffect(state) {
                            try {
                                heartRateChangeViewModel.reset()
                            } catch (exception: Exception) {
                                android.util.Log.e("WorkoutScreen", "Error resetting heart rate change view model", exception)
                            }
                        }

                        if (showRestScreenTutorial) {
                            TutorialOverlay(
                                visible = true,
                                text = "Rest timer\nStarts on its own.\nLong-press the time to edit, then use +/−.\n\nExercises\nCurrent and upcoming exercises are shown.\nTap the left or right side to see previous or next.\n\nHeads-up\nScreen lights up with 5 seconds left.\n\nSkip rest\nDouble-press the back button to continue early.",
                                onDismiss = onDismissRestScreenTutorial,
                                hapticsViewModel = hapticsViewModel
                            )
                        } else {
                            RestScreen(
                                viewModel = viewModel,
                                hapticsViewModel = hapticsViewModel,
                                state = state,
                                hearthRateChart = { heartRateChartComposable() },
                                onTimerEnd = {
                                    try {
                                        viewModel.storeSetData()
                                        viewModel.pushAndStoreWorkoutData(false,context){
                                            try {
                                                viewModel.goToNextState()
                                                viewModel.lightScreenUp()
                                            } catch (exception: Exception) {
                                                android.util.Log.e("WorkoutScreen", "Error in onTimerEnd callback", exception)
                                            }
                                        }
                                    } catch (exception: Exception) {
                                        android.util.Log.e("WorkoutScreen", "Error handling timer end", exception)
                                    }
                                },
                                navController = navController,
                            )
                        }
                    }
                    is WorkoutState.Completed -> {
                        val state = workoutState as WorkoutState.Completed
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
}