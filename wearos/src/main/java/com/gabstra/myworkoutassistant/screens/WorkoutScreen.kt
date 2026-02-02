package com.gabstra.myworkoutassistant.screens

import android.content.Context
import android.widget.Toast
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
import androidx.compose.runtime.rememberCoroutineScope
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
import com.gabstra.myworkoutassistant.composables.HeartRateStatus
import com.gabstra.myworkoutassistant.composables.HrStatusBadge
import com.gabstra.myworkoutassistant.composables.HrTargetGlowEffect
import com.gabstra.myworkoutassistant.composables.LifecycleObserver
import com.gabstra.myworkoutassistant.composables.LoadingOverlay
import com.gabstra.myworkoutassistant.composables.SyncStatusBadge
import com.gabstra.myworkoutassistant.composables.TutorialOverlay
import com.gabstra.myworkoutassistant.composables.TutorialStep
import com.gabstra.myworkoutassistant.composables.WorkoutStateHeader
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.PolarViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.SensorDataViewModel
import com.gabstra.myworkoutassistant.data.cancelWorkoutInProgressNotification
import com.gabstra.myworkoutassistant.data.showWorkoutInProgressNotification
import com.gabstra.myworkoutassistant.notifications.WorkoutNotificationHelper
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.viewmodels.HeartRateChangeViewModel
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import com.gabstra.myworkoutassistant.shared.viewmodels.applyCalibrationRIR
import com.gabstra.myworkoutassistant.shared.viewmodels.confirmCalibrationLoad
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch

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
    var hrStatus by remember { mutableStateOf<HeartRateStatus?>(null) }
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val screenState by viewModel.screenState.collectAsState()
    val workoutState = screenState.workoutState
    val selectedWorkout = screenState.selectedWorkout
    val userAge = screenState.userAge
    val hasPolarApiBeenInitialized by polarViewModel.hasBeenInitialized.collectAsState()
    val isResuming = screenState.isResuming
    val isRefreshing = screenState.isRefreshing
    val isSyncingToPhone by viewModel.isSyncingToPhone

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
                upperBoundMaxHRPercent,
                onHrStatusChange = { status -> hrStatus = status }
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
                upperBoundMaxHRPercent,
                onHrStatusChange = { status -> hrStatus = status }
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
            // Flush any pending sync before navigating away
            scope.launch {
                viewModel.flushWorkoutSync()
            }
            navController.navigate(Screen.WorkoutSelection.route){
                popUpTo(0) {
                    inclusive = true
                }
            }
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
            
                when (workoutState) {
                is WorkoutState.Set -> {
                    viewModel.openCustomDialog()
                    viewModel.lightScreenUp()
                }
                is WorkoutState.Rest -> {
                    viewModel.openCustomDialog()
                    viewModel.lightScreenUp()
                }
                is WorkoutState.CalibrationLoadSelection -> {
                    Toast.makeText(context, "Double press to confirm load", Toast.LENGTH_SHORT).show()
                }
                is WorkoutState.CalibrationRIRSelection -> {
                    Toast.makeText(context, "Double press to confirm RIR", Toast.LENGTH_SHORT).show()
                }
                else -> {
                    // Keep existing behavior for other states
                    viewModel.openCustomDialog()
                    viewModel.lightScreenUp()
                }
            }
        },
        onDoublePress = {
            android.util.Log.d("WorkoutSync", "Double-press back button detected, workoutState: $workoutState")
            if(workoutState is WorkoutState.Completed || isCustomDialogOpen) return@CustomBackHandler
            
            when (workoutState) {
                is WorkoutState.Set -> {
                    // Set completion now handled by single-press dialog in ExerciseScreen
                    // No-op for double-press
                }
                is WorkoutState.CalibrationLoadSelection -> {
                    // CalibrationLoadSelectionScreen handles its own back button logic
                    // This case should not be reached, but handle it gracefully
                }
                is WorkoutState.CalibrationRIRSelection -> {
                    // CalibrationRIRScreen handles its own back button logic
                    // This case should not be reached, but handle it gracefully
                }
                is WorkoutState.Rest -> {
                    // Rest skip now handled by single-press dialog in RestScreen
                    // No-op for double-press
                }
                else -> {
                    // Keep existing behavior for other states (pause workout)
                    showWorkoutInProgressDialog = true
                    viewModel.pauseWorkout()
                    viewModel.lightScreenUp()
                }
            }
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
                steps = listOf(
                    TutorialStep("Heart rate (left)", "Tap the number to change the display format."),
                    TutorialStep("Workout progress (right)", "See your current position in the workout."),
                    TutorialStep("Back button", "Double-press to complete the set.")
                ),
                onDismiss = onDismissHeartRateTutorial,
                hapticsViewModel = hapticsViewModel,
                onVisibilityChange = { isVisible ->
                    if (isVisible) {
                        viewModel.setDimming(false)
                    } else {
                        viewModel.reEvaluateDimmingForCurrentState()
                    }
                }
            )
        } else {
            val stateTypeKey = remember(workoutState) {
                when (workoutState) {
                    is WorkoutState.Preparing -> "Preparing"
                    is WorkoutState.Set -> "Set"
                    is WorkoutState.Rest -> "Rest"
                    is WorkoutState.Completed -> "Completed"
                    is WorkoutState.CalibrationLoadSelection -> "Calibration Load Selection"
                    is WorkoutState.CalibrationRIRSelection -> "Calibration RIR Selection"
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
                        val state = workoutState
                        if(!selectedWorkout.usePolarDevice)
                            PreparingStandardScreen(viewModel,hapticsViewModel,hrViewModel,state)
                        else
                            PreparingPolarScreen(viewModel,hapticsViewModel,navController,polarViewModel,state)
                    }
                    is WorkoutState.CalibrationLoadSelection -> {
                        val state = workoutState
                        CalibrationLoadScreen(
                            viewModel = viewModel,
                            hapticsViewModel = hapticsViewModel,
                            state = state,
                            navController = navController,
                            hearthRateChart = {
                                heartRateChartComposable(state.lowerBoundMaxHRPercent, state.upperBoundMaxHRPercent)
                            },
                            onWeightSelected = { selectedWeight ->
                                // Update set data with selected weight
                                val newSetData = when (val currentData = state.currentSetData) {
                                    is WeightSetData -> currentData.copy(actualWeight = selectedWeight)
                                    is BodyWeightSetData -> currentData.copy(additionalWeight = selectedWeight)
                                    else -> currentData
                                }
                                val updatedSetData = when (newSetData) {
                                    is WeightSetData -> newSetData.copy(volume = newSetData.calculateVolume())
                                    is BodyWeightSetData -> newSetData.copy(volume = newSetData.calculateVolume())
                                    else -> newSetData
                                }
                                state.currentSetData = updatedSetData
                                // Move directly to set execution (or warmups if enabled)
                                viewModel.confirmCalibrationLoad()
                            }
                        )
                    }
                    is WorkoutState.CalibrationRIRSelection -> {
                        val state = workoutState as WorkoutState.CalibrationRIRSelection
                        CalibrationRIRScreen(
                            viewModel = viewModel,
                            hapticsViewModel = hapticsViewModel,
                            state = state,
                            navController = navController,
                            hearthRateChart = {
                                heartRateChartComposable(state.lowerBoundMaxHRPercent, state.upperBoundMaxHRPercent)
                            },
                            onRIRConfirmed = { rir, formBreaks ->
                                // Apply calibration RIR adjustments
                                viewModel.applyCalibrationRIR(rir, formBreaks)
                            }
                        )
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
                                steps = listOf(
                                    TutorialStep("Navigate pages", "Swipe left or right to move between views."),
                                    TutorialStep("Scroll long text", "Tap the exercise title or header to scroll."),
                                    TutorialStep("Auto-return", "You'll return to workout details after 10 seconds of inactivity."),
                                    TutorialStep("Complete the set", "Tap 'Complete Set' or press the back button when done.")
                                ),
                                onDismiss = onDismissSetScreenTutorial,
                                hapticsViewModel = hapticsViewModel,
                                onVisibilityChange = { isVisible ->
                                    if (isVisible) {
                                        viewModel.setDimming(false)
                                    } else {
                                        viewModel.reEvaluateDimmingForCurrentState()
                                    }
                                }
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
                                steps = listOf(
                                    TutorialStep("Rest timer", "Automatically starts counting down.\nLong-press the timer to adjust it, then use +/- buttons."),
                                    TutorialStep("Exercise preview", "See your current and next exercises.\nTap the left or right side to view previous or upcoming exercises."),
                                    TutorialStep("Reminder", "Your screen will light up when 5 seconds remain."),
                                    TutorialStep("Skip rest", "Double-press the back button to skip ahead.")
                                ),
                                onDismiss = onDismissRestScreenTutorial,
                                hapticsViewModel = hapticsViewModel,
                                onVisibilityChange = { isVisible ->
                                    if (isVisible) {
                                        viewModel.setDimming(false)
                                    } else {
                                        viewModel.reEvaluateDimmingForCurrentState()
                                    }
                                }
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
                                        val isDone = viewModel.isNextStateCompleted()
                                        viewModel.pushAndStoreWorkoutData(isDone, context){
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
        
        LoadingOverlay(isVisible = isSyncingToPhone, text = "Syncing")
        
        // Sync status badge (non-blocking)
        SyncStatusBadge(viewModel = viewModel)
        
        // HR target indicators (non-blocking)
        HrTargetGlowEffect(isVisible = hrStatus != null)
        HrStatusBadge(hrStatus = hrStatus)
    }
}
