package com.gabstra.myworkoutassistant.screens

import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.zIndex
import androidx.navigation.NavController
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import androidx.wear.tooling.preview.devices.WearDevices
import com.gabstra.myworkoutassistant.MyApplication
import com.gabstra.myworkoutassistant.composables.CustomBackHandler
import com.gabstra.myworkoutassistant.composables.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.composables.ExternalHeartRateDisconnectDialog
import com.gabstra.myworkoutassistant.composables.HeartRateExternal
import com.gabstra.myworkoutassistant.composables.HeartRateStandard
import com.gabstra.myworkoutassistant.composables.HeartRateStatus
import com.gabstra.myworkoutassistant.composables.HrStatusBadge
import com.gabstra.myworkoutassistant.composables.HrTargetGlowEffect
import com.gabstra.myworkoutassistant.composables.LifecycleObserver
import com.gabstra.myworkoutassistant.composables.LocalTopOverlayController
import com.gabstra.myworkoutassistant.composables.TopOverlayHost
import com.gabstra.myworkoutassistant.composables.TutorialOverlay
import com.gabstra.myworkoutassistant.composables.TutorialStep
import com.gabstra.myworkoutassistant.composables.WorkoutPagerLayoutTokens
import com.gabstra.myworkoutassistant.composables.WorkoutStateHeader
import com.gabstra.myworkoutassistant.composables.rememberTopOverlayController
import com.gabstra.myworkoutassistant.composables.rememberWearCoroutineScope
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.ExternalHeartRateConnectionState
import com.gabstra.myworkoutassistant.data.ExternalHeartRateDeviceController
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.PolarViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.SensorDataViewModel
import com.gabstra.myworkoutassistant.data.WhoopHeartRateViewModel
import com.gabstra.myworkoutassistant.data.cancelWorkoutInProgressNotification
import com.gabstra.myworkoutassistant.data.isReady
import com.gabstra.myworkoutassistant.data.showTimerCompletedNotification
import com.gabstra.myworkoutassistant.data.showWorkoutInProgressNotification
import com.gabstra.myworkoutassistant.notifications.WorkoutNotificationHelper
import com.gabstra.myworkoutassistant.presentation.theme.MyWorkoutAssistantTheme
import com.gabstra.myworkoutassistant.shared.HeartRateSource
import com.gabstra.myworkoutassistant.shared.formatWeight
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.viewmodels.HeartRateChangeViewModel
import com.gabstra.myworkoutassistant.shared.workout.calibration.applyCalibrationRIR
import com.gabstra.myworkoutassistant.shared.workout.calibration.confirmCalibrationLoad
import com.gabstra.myworkoutassistant.shared.workout.display.formatWorkoutDurationSecondsForDisplay
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workout.ui.WorkoutScreenState
import com.google.android.horologist.compose.ambient.AmbientAwareTime
import com.google.android.horologist.compose.ambient.AmbientState
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch
import java.time.format.DateTimeFormatter

@OptIn(ExperimentalCoroutinesApi::class)
@Composable
fun WorkoutScreen(
    navController: NavController,
    viewModel : AppViewModel,
    hapticsViewModel: HapticsViewModel,
    heartRateChangeViewModel : HeartRateChangeViewModel,
    hrViewModel: SensorDataViewModel,
    polarViewModel: PolarViewModel,
    whoopHeartRateViewModel: WhoopHeartRateViewModel,
    showHeartRateTutorial: Boolean,
    onDismissHeartRateTutorial: () -> Unit,
    showSetScreenTutorial: Boolean,
    onDismissSetScreenTutorial: () -> Unit,
    showRestScreenTutorial: Boolean,
    onDismissRestScreenTutorial: () -> Unit,
){
    var showWorkoutInProgressDialog by remember { mutableStateOf(false) }

    val context = LocalContext.current
    val scope = rememberWearCoroutineScope()
    val screenState by viewModel.screenState.collectAsState()
    val workoutState = screenState.workoutState
    var hrStatus by remember(workoutState) { mutableStateOf<HeartRateStatus?>(null) }
    val selectedWorkout = screenState.selectedWorkout
    val userAge = screenState.userAge
    val measuredMaxHeartRate = screenState.measuredMaxHeartRate
    val restingHeartRate = screenState.restingHeartRate
    val activeExternalHeartRateController: ExternalHeartRateDeviceController? =
        when (selectedWorkout.heartRateSource) {
            HeartRateSource.POLAR_BLE -> polarViewModel
            HeartRateSource.WHOOP_BLE -> whoopHeartRateViewModel
            HeartRateSource.WATCH_SENSOR -> null
        }
    val hasExternalSourceBeenInitialized by (
        activeExternalHeartRateController?.hasBeenInitialized?.collectAsState()
            ?: remember { mutableStateOf(false) }
        )
    val externalConnectionState by (
        activeExternalHeartRateController?.connectionState?.collectAsState()
            ?: remember {
                mutableStateOf<ExternalHeartRateConnectionState>(
                    ExternalHeartRateConnectionState.Idle
                )
            }
        )
    val externalSkipped by (
        activeExternalHeartRateController?.isSkippedForSession?.collectAsState()
            ?: remember { mutableStateOf(false) }
        )
    val externalHasEverConnected by (
        activeExternalHeartRateController?.hasEverConnectedThisSession?.collectAsState()
            ?: remember { mutableStateOf(false) }
        )
    val isResuming = screenState.isResuming
    val isRefreshing = screenState.isRefreshing
    var showExternalDisconnectDialog by remember { mutableStateOf(false) }
    val shouldShowExternalDisconnectPrompt = selectedWorkout.usesExternalHeartRateDevice &&
        externalHasEverConnected &&
        !externalSkipped &&
        workoutState !is WorkoutState.Preparing &&
        workoutState !is WorkoutState.Completed &&
        externalConnectionState is ExternalHeartRateConnectionState.Error
    val onBeforeGoHome = remember(selectedWorkout) {
        {
            // Ensure no timer background loop remains active after leaving workout flow.
                viewModel.workoutTimerService.unregisterAll()
            try {
                if (selectedWorkout.usesExternalHeartRateDevice) {
                    activeExternalHeartRateController?.disconnectFromDevice()
                } else {
                    hrViewModel.stopMeasuringHeartRate()
                }
            } catch (exception: Exception) {
                android.util.Log.e("WorkoutScreen", "Error stopping sensors on Go Home", exception)
            }
            Unit
        }
    }

    DisposableEffect(Unit) {
        onDispose {
            // Defensive cleanup for any navigation path that leaves WorkoutScreen.
            viewModel.workoutTimerService.unregisterAll()
        }
    }

    val triggerMobileNotification = screenState.enableWorkoutNotificationFlow
    val topOverlayController = rememberTopOverlayController()

    LaunchedEffect(triggerMobileNotification){
        if(triggerMobileNotification==null) return@LaunchedEffect
        try {
            val notificationHelper = WorkoutNotificationHelper(context)
            notificationHelper.clearChannelNotifications()
            showWorkoutInProgressNotification(context, selectedWorkout.globalId)
        } catch (exception: Exception) {
            android.util.Log.e("WorkoutScreen", "Error showing workout notification", exception)
        }
    }

    LaunchedEffect(selectedWorkout.globalId) {
        try {
            showWorkoutInProgressNotification(context, selectedWorkout.globalId)
        } catch (exception: Exception) {
            android.util.Log.e("WorkoutScreen", "Error refreshing workout notification", exception)
        }
    }

    @Composable
    fun heartRateChartComposable(
        modifier: Modifier = Modifier,
        lowerBoundMaxHRPercent: Float? = null,
        upperBoundMaxHRPercent: Float? = null
    ){
        if(selectedWorkout.usesExternalHeartRateDevice && activeExternalHeartRateController != null){
            HeartRateExternal(
                modifier = modifier,
                appViewModel = viewModel,
                hapticsViewModel = hapticsViewModel,
                heartRateChangeViewModel = heartRateChangeViewModel,
                externalHeartRateController = activeExternalHeartRateController,
                userAge = userAge,
                measuredMaxHeartRate = measuredMaxHeartRate,
                restingHeartRate = restingHeartRate,
                lowerBoundMaxHRPercent = lowerBoundMaxHRPercent,
                upperBoundMaxHRPercent = upperBoundMaxHRPercent,
                onHrStatusChange = { status -> hrStatus = status }
            )
        }else{
            HeartRateStandard(
                modifier = modifier,
                appViewModel = viewModel,
                hapticsViewModel = hapticsViewModel,
                heartRateChangeViewModel = heartRateChangeViewModel,
                hrViewModel = hrViewModel,
                userAge = userAge,
                measuredMaxHeartRate = measuredMaxHeartRate,
                restingHeartRate = restingHeartRate,
                lowerBoundMaxHRPercent = lowerBoundMaxHRPercent,
                upperBoundMaxHRPercent = upperBoundMaxHRPercent,
                onHrStatusChange = { status -> hrStatus = status }
            )
        }
    }

    CustomDialogYesOnLongPress(
        show = showWorkoutInProgressDialog,
        title = "Workout in progress",
        handleYesClick = {
            hapticsViewModel.doGentleVibration()

            //viewModel.pushAndStoreWorkoutData(false,context)
            try {
                if(!selectedWorkout.usesExternalHeartRateDevice){
                    hrViewModel.stopMeasuringHeartRate()
                }else{
                    activeExternalHeartRateController?.disconnectFromDevice()
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

    LaunchedEffect(shouldShowExternalDisconnectPrompt, externalConnectionState) {
        if (shouldShowExternalDisconnectPrompt && !showExternalDisconnectDialog) {
            showExternalDisconnectDialog = true
            viewModel.pauseWorkout()
            viewModel.lightScreenUp()
        } else if (
            showExternalDisconnectDialog &&
            (externalConnectionState.isReady || externalSkipped)
        ) {
            showExternalDisconnectDialog = false
            viewModel.resumeWorkout()
        }
    }

    ExternalHeartRateDisconnectDialog(
        show = showExternalDisconnectDialog,
        title = "${selectedWorkout.heartRateSource.displayName()} disconnected",
        message = when (externalConnectionState) {
            is ExternalHeartRateConnectionState.Error ->
                (externalConnectionState as ExternalHeartRateConnectionState.Error).message
            else -> "Your external heart-rate source is unavailable."
        },
        onRetry = {
            hapticsViewModel.doGentleVibration()
            activeExternalHeartRateController?.retryConnection()
        },
        onContinueWithoutSensor = {
            hapticsViewModel.doGentleVibration()
            activeExternalHeartRateController?.skipConnectionForSession()
            showExternalDisconnectDialog = false
            viewModel.resumeWorkout()
        },
        onEndWorkout = {
            hapticsViewModel.doGentleVibration()
            activeExternalHeartRateController?.disconnectFromDevice()
            cancelWorkoutInProgressNotification(context)
            scope.launch {
                viewModel.flushWorkoutSync()
            }
            navController.navigate(Screen.WorkoutSelection.route) {
                popUpTo(0) { inclusive = true }
            }
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
                    Toast.makeText(context, "Double-press to confirm the weight.", Toast.LENGTH_SHORT).show()
                }
                is WorkoutState.CalibrationRIRSelection -> {
                    Toast.makeText(context, "Double-press to confirm RIR.", Toast.LENGTH_SHORT).show()
                }
                is WorkoutState.AutoRegulationRIRSelection -> {
                    Toast.makeText(context, "Double-press to confirm RIR.", Toast.LENGTH_SHORT).show()
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
                }
                is WorkoutState.AutoRegulationRIRSelection -> {
                    // AutoRegulationRIRScreen handles its own back button logic
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
                viewModel.workoutTimerService.pauseForBackground()
                if(!selectedWorkout.usesExternalHeartRateDevice){
                    hrViewModel.stopMeasuringHeartRate()
                }
                // Flush timer state to database before app pauses/closes
                // This ensures timer progress is persisted even if app is killed
                scope.launch {
                    try {
                        viewModel.flushTimerState()
                        // Persist a fresh recovery snapshot after timer flush so process-death
                        // recovery uses the exact paused timer value.
                        viewModel.persistRecoverySnapshotNow(synchronous = true)
                    } catch (exception: Exception) {
                        android.util.Log.e("WorkoutScreen", "Error flushing timer state", exception)
                    }
                }
            } catch (exception: Exception) {
                android.util.Log.e("WorkoutScreen", "Error stopping heart rate measurement", exception)
            }
        },
        onResumed = {
            try {
                viewModel.workoutTimerService.resumeFromBackground()
                if(!selectedWorkout.usesExternalHeartRateDevice){
                    hrViewModel.startMeasuringHeartRate()
                }
                else if(hasExternalSourceBeenInitialized && !externalSkipped){
                    activeExternalHeartRateController?.foregroundEntered()
                    activeExternalHeartRateController?.connectToDevice()
                }
            } catch (exception: Exception) {
                android.util.Log.e("WorkoutScreen", "Error resuming heart-rate source", exception)
            }
        }
    )

    // Ambient mode is intentionally disabled while KeepOn owns the active workout screen.
    CompositionLocalProvider(LocalTopOverlayController provides topOverlayController) {
            LaunchedEffect(showHeartRateTutorial) {
                if (showHeartRateTutorial) {
                    viewModel.setDimming(false)
                    topOverlayController.show(owner = "workout_heart_rate_tutorial") {
                        TutorialOverlay(
                            visible = true,
                            steps = listOf(
                                TutorialStep("Heart rate (left)", "Tap the number to cycle display (for example BPM or zone)."),
                                TutorialStep("Progress (right)", "Shows which exercise and set you are on."),
                                TutorialStep("Complete this set", "Tap Complete Set, or press back once and hold the checkmark to confirm.")
                            ),
                            onDismiss = onDismissHeartRateTutorial,
                            hapticsViewModel = hapticsViewModel
                        )
                    }
                } else {
                    topOverlayController.clear("workout_heart_rate_tutorial")
                    viewModel.reEvaluateDimmingForCurrentState()
                }
            }

            Box(
                modifier = Modifier
                    .fillMaxSize(),
            ) {
            if(isResuming){
                LoadingScreen(viewModel,"Resuming your workout")
                return@Box
            }

            if(isRefreshing){
                LoadingScreen(viewModel,"Reloading your workout")
                return@Box
            }

            val stateTypeKey = remember(workoutState) {
                when (workoutState) {
                    is WorkoutState.Preparing -> "Preparing"
                    is WorkoutState.Set -> "Set"
                    is WorkoutState.Rest -> "Rest"
                    is WorkoutState.Completed -> "Completed"
                    is WorkoutState.CalibrationLoadSelection -> "Calibration Load Selection"
                    is WorkoutState.CalibrationRIRSelection -> "Calibration RIR Selection"
                    is WorkoutState.AutoRegulationRIRSelection -> "Auto-regulation RIR"
                }
            }

            key(stateTypeKey) {
                Box(modifier = Modifier.fillMaxSize()) {
                    Box(
                        modifier = Modifier
                            .align(Alignment.TopCenter)
                            .fillMaxWidth()
                            .height(WorkoutPagerLayoutTokens.WorkoutHeaderTopPadding+WorkoutPagerLayoutTokens.WorkoutHeaderHeight)
                            .background(MaterialTheme.colorScheme.background)
                            .zIndex(1f),
                        contentAlignment = Alignment.Center
                    ) {
                        WorkoutStateHeader(
                            modifier = Modifier.padding(top = WorkoutPagerLayoutTokens.WorkoutHeaderTopPadding),
                            workoutState = workoutState,
                            viewModel = viewModel,
                            hapticsViewModel = hapticsViewModel
                        )
                    }

                    Box(
                        modifier = Modifier.fillMaxSize()
                    ) {
                        when(workoutState){
                            is WorkoutState.Preparing -> {
                                if(!selectedWorkout.usesExternalHeartRateDevice)
                                    PreparingStandardScreen(viewModel,hapticsViewModel,hrViewModel,
                                        workoutState
                                    )
                                else if (activeExternalHeartRateController != null)
                                    PreparingExternalHeartRateScreen(
                                        viewModel,
                                        hapticsViewModel,
                                        navController,
                                        activeExternalHeartRateController,
                                        workoutState
                                    )
                            }
                            is WorkoutState.CalibrationLoadSelection -> {
                                CalibrationLoadScreen(
                                    viewModel = viewModel,
                                    hapticsViewModel = hapticsViewModel,
                                    state = workoutState,
                                    navController = navController,
                                    onBeforeGoHome = onBeforeGoHome,
                                    hearthRateChart = { modifier ->
                                        heartRateChartComposable(
                                            modifier = modifier,
                                            lowerBoundMaxHRPercent = workoutState.lowerBoundMaxHRPercent,
                                            upperBoundMaxHRPercent = workoutState.upperBoundMaxHRPercent
                                        )
                                    },
                                    onWeightSelected = { selectedWeight ->
                                        // Update set data with selected weight
                                        val newSetData = when (val currentData =
                                            workoutState.currentSetData) {
                                            is WeightSetData -> currentData.copy(actualWeight = selectedWeight)
                                            is BodyWeightSetData -> currentData.copy(additionalWeight = selectedWeight)
                                            else -> currentData
                                        }
                                        val updatedSetData = when (newSetData) {
                                            is WeightSetData -> newSetData.copy(volume = newSetData.calculateVolume())
                                            is BodyWeightSetData -> newSetData.copy(volume = newSetData.calculateVolume())
                                            else -> newSetData
                                        }
                                        workoutState.currentSetData = updatedSetData
                                        // Move directly to set execution (or warmups if enabled)
                                        viewModel.confirmCalibrationLoad()
                                    }
                                )
                            }
                            is WorkoutState.CalibrationRIRSelection -> {
                                CalibrationRIRScreen(
                                    viewModel = viewModel,
                                    hapticsViewModel = hapticsViewModel,
                                    state = workoutState,
                                    navController = navController,
                                    onBeforeGoHome = onBeforeGoHome,
                                    hearthRateChart = { modifier ->
                                        heartRateChartComposable(
                                            modifier = modifier,
                                            lowerBoundMaxHRPercent = workoutState.lowerBoundMaxHRPercent,
                                            upperBoundMaxHRPercent = workoutState.upperBoundMaxHRPercent
                                        )
                                    },
                                    onRIRConfirmed = { rir, formBreaks ->
                                        viewModel.applyCalibrationRIR(rir, formBreaks)
                                    }
                                )
                            }
                            is WorkoutState.AutoRegulationRIRSelection -> {
                                AutoRegulationRIRScreen(
                                    viewModel = viewModel,
                                    hapticsViewModel = hapticsViewModel,
                                    state = workoutState,
                                    navController = navController,
                                    onBeforeGoHome = onBeforeGoHome,
                                    hearthRateChart = { modifier ->
                                        heartRateChartComposable(
                                            modifier = modifier,
                                            lowerBoundMaxHRPercent = workoutState.lowerBoundMaxHRPercent,
                                            upperBoundMaxHRPercent = workoutState.upperBoundMaxHRPercent
                                        )
                                    },
                                )
                            }
                            is WorkoutState.Set -> {
                                LaunchedEffect(workoutState) {
                                    try {
                                        heartRateChangeViewModel.reset()
                                    } catch (exception: Exception) {
                                        android.util.Log.e("WorkoutScreen", "Error resetting heart rate change view model", exception)
                                    }
                                }

                                LaunchedEffect(showSetScreenTutorial) {
                                    if (showSetScreenTutorial) {
                                        viewModel.setDimming(false)
                                        topOverlayController.show(owner = "workout_set_tutorial") {
                                            TutorialOverlay(
                                                visible = true,
                                                steps = listOf(
                                                    TutorialStep("Extra pages", "Swipe left or right for more views for this set."),
                                                    TutorialStep("Long exercise names", "Tap the exercise title or top bar to scroll the text."),
                                                    TutorialStep("Save the set", "Use Complete Set on the buttons page, or press back once and hold the checkmark.")
                                                ),
                                                onDismiss = onDismissSetScreenTutorial,
                                                hapticsViewModel = hapticsViewModel
                                            )
                                        }
                                    } else {
                                        topOverlayController.clear("workout_set_tutorial")
                                        viewModel.reEvaluateDimmingForCurrentState()
                                    }
                                }

                                DisposableEffect(Unit) {
                                    onDispose {
                                        topOverlayController.clear("workout_set_tutorial")
                                    }
                                }

                                if (!showSetScreenTutorial) {
                                    key(workoutState.exerciseId) {
                                        ExerciseScreen(
                                            viewModel = viewModel,
                                            hapticsViewModel = hapticsViewModel,
                                            state = workoutState,
                                            hearthRateChart = { modifier ->
                                                heartRateChartComposable(
                                                    modifier = modifier,
                                                    lowerBoundMaxHRPercent = workoutState.lowerBoundMaxHRPercent,
                                                    upperBoundMaxHRPercent = workoutState.upperBoundMaxHRPercent
                                                )
                                            },
                                            navController = navController,
                                            onBeforeGoHome = onBeforeGoHome,
                                        )
                                    }
                                }
                            }
                            is WorkoutState.Rest -> {
                                LaunchedEffect(workoutState) {
                                    try {
                                        heartRateChangeViewModel.reset()
                                    } catch (exception: Exception) {
                                        android.util.Log.e("WorkoutScreen", "Error resetting heart rate change view model", exception)
                                    }
                                }

                                LaunchedEffect(showRestScreenTutorial, workoutState.set.id) {
                                    if (showRestScreenTutorial) {
                                        viewModel.setDimming(false)
                                        topOverlayController.show(owner = "workout_rest_tutorial") {
                                            TutorialOverlay(
                                                visible = true,
                                                steps = listOf(
                                                    TutorialStep("Rest timer", "Countdown starts on its own.\nLong press the timer, then use + and − to adjust."),
                                                    TutorialStep("Exercise preview", "Tap the left or right side to see the previous or next exercise."),
                                                    TutorialStep("Almost done", "The screen turns on when 5 seconds remain."),
                                                    TutorialStep("Skip this rest", "Press back once, then hold the checkmark to skip early.")
                                                ),
                                                onDismiss = onDismissRestScreenTutorial,
                                                hapticsViewModel = hapticsViewModel
                                            )
                                        }
                                    } else {
                                        topOverlayController.clear("workout_rest_tutorial")
                                        viewModel.reEvaluateDimmingForCurrentState()
                                    }
                                }

                                RestScreen(
                                    viewModel = viewModel,
                                    hapticsViewModel = hapticsViewModel,
                                    state = workoutState,
                                    hearthRateChart = { modifier ->
                                        heartRateChartComposable(modifier = modifier)
                                    },
                                    onBeforeGoHome = onBeforeGoHome,
                                    onTimerEnd = {
                                        try {
                                            if (!MyApplication.isAppInForeground()) {
                                                showTimerCompletedNotification(
                                                    context = context,
                                                    title = "Rest finished",
                                                    message = "Time for your next set"
                                                )
                                            }
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
                            is WorkoutState.Completed -> {
                                WorkoutCompleteScreen(
                                    navController,
                                    viewModel,
                                    workoutState,
                                    hrViewModel,
                                    hapticsViewModel,
                                    activeExternalHeartRateController
                                )
                            }
                        }
                    }
                }
            }
            // Sync status badge (non-blocking)
            //SyncStatusBadge(viewModel = viewModel)

            // HR target indicators (non-blocking)
            HrTargetGlowEffect(isVisible = hrStatus != null)
            HrStatusBadge(hrStatus = hrStatus)

            TopOverlayHost(controller = topOverlayController)

            // AmbientWorkoutOverlay remains below for future re-enablement, but is not rendered.
        }
    }
}

@Composable
private fun AmbientWorkoutOverlay(
    ambientState: AmbientState,
    screenState: WorkoutScreenState,
    viewModel: AppViewModel
) {
    val workoutState = screenState.workoutState
    val exerciseName = remember(workoutState, viewModel.exercisesById) {
        val exerciseId = when (workoutState) {
            is WorkoutState.Set -> workoutState.exerciseId
            is WorkoutState.Rest -> workoutState.exerciseId
            is WorkoutState.CalibrationLoadSelection -> workoutState.exerciseId
            is WorkoutState.CalibrationRIRSelection -> workoutState.exerciseId
            is WorkoutState.AutoRegulationRIRSelection -> workoutState.exerciseId
            else -> null
        }
        exerciseId?.let { viewModel.exercisesById[it]?.name }
    }
    val phaseText = remember(workoutState) { ambientPhaseText(workoutState) }
    val detailText = remember(workoutState) { ambientDetailText(workoutState) }
    val progressText = remember(workoutState, viewModel.allWorkoutStates.size) {
        val stateIndex = viewModel.allWorkoutStates.indexOfFirst { it === workoutState }
        if (stateIndex >= 0 && viewModel.allWorkoutStates.isNotEmpty()) {
            "${stateIndex + 1}/${viewModel.allWorkoutStates.size}"
        } else {
            null
        }
    }
    val setCounterText = remember(workoutState) {
        (workoutState as? WorkoutState.Set)
            ?.let { state ->
                viewModel.getSetCounterForExercise(state.exerciseId, state)
                    ?.let { (current, total) -> if (total > 1) "Set $current/$total" else "Set $current" }
            }
    }
    val overlayModel = ambientOverlayModel(
        workoutState = workoutState,
        exerciseName = exerciseName,
        metadataText = setCounterText ?: detailText ?: progressText,
        progressText = progressText,
        formatWeightForState = { weight, equipmentId ->
            equipmentId
                ?.let { viewModel.getEquipmentById(it) }
                ?.formatWeight(weight)
                ?: formatWeight(weight)
        }
    )
    val timeFormatter = remember { DateTimeFormatter.ofPattern("HH:mm") }

    AmbientWorkoutOverlayContent(
        ambientState = ambientState,
        model = overlayModel.copy(phaseText = phaseText),
        timeContent = {
            AmbientAwareTime(stateUpdate = ambientState) { dateTime, _ ->
                AmbientWorkoutTimeText(timeFormatter.format(dateTime))
            }
        }
    )
}

@Composable
private fun AmbientWorkoutOverlayContent(
    ambientState: AmbientState,
    model: AmbientWorkoutOverlayModel,
    timeContent: @Composable () -> Unit
) {
    val offsetDp = (ambientState as? AmbientState.Ambient)
        ?.takeIf { it.burnInProtectionRequired }
        ?.let { (((it.updateTimeMillis / 60_000L) % 3L) - 1L).toInt().dp }
        ?: 0.dp

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black)
            .semantics { contentDescription = "Ambient workout overlay" }
            .zIndex(20f),
        contentAlignment = Alignment.TopCenter
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .offset(x = offsetDp, y = -offsetDp),
            verticalArrangement = Arrangement.Top,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(28.dp)
                    .padding(horizontal = 24.dp),
                contentAlignment = Alignment.Center
            ) {
                timeContent()
            }

            Text(
                modifier = Modifier.semantics {
                    contentDescription = "Ambient workout exercise: ${model.exerciseName.orEmpty()}"
                },
                text = model.exerciseName.orEmpty(),
                color = Color.White,
                style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.SemiBold),
                maxLines = 1,
                textAlign = TextAlign.Center,
                overflow = TextOverflow.Ellipsis
            )
            Spacer(modifier = Modifier.height(2.5.dp))
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 32.dp)
                    .semantics {
                        contentDescription = "Ambient workout phase: ${model.phaseText}"
                    },
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = model.phaseText.uppercase(),
                    color = Color.White,
                    style = MaterialTheme.typography.bodyExtraSmall.copy(fontWeight = FontWeight.Medium),
                    maxLines = 1,
                    textAlign = TextAlign.Center,
                    overflow = TextOverflow.Ellipsis
                )

                if (!model.metadataText.isNullOrBlank()) {
                    Spacer(modifier = Modifier.width(5.dp))
                    Text(
                        text = model.metadataText,
                        color = Color.White,
                        style = MaterialTheme.typography.bodyExtraSmall.copy(fontWeight = FontWeight.Medium),
                        maxLines = 1,
                        textAlign = TextAlign.Center,
                        overflow = TextOverflow.Ellipsis
                    )
                }
            }

            Spacer(Modifier.size(15.dp))

            AmbientWorkoutMetricsRow(metrics = model.metrics)

            if (!model.progressText.isNullOrBlank()) {
                Spacer(Modifier.size(10.dp))
                Text(
                    text = "${model.progressText}",
                    color = Color.White,
                    style = MaterialTheme.typography.labelSmall,
                    maxLines = 1,
                    textAlign = TextAlign.Center
                )
            }
        }
    }
}

@Composable
private fun AmbientWorkoutMetricsRow(metrics: List<AmbientWorkoutMetric>) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.Bottom,
        horizontalArrangement = Arrangement.spacedBy(20.dp, Alignment.CenterHorizontally)
    ) {
        metrics.forEach { metric ->
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(2.5.dp, Alignment.Bottom)
            ) {
                Text(
                    text = metric.label,
                    color = Color.White,
                    style = MaterialTheme.typography.bodyExtraSmall,
                    textAlign = TextAlign.Center,
                    maxLines = 1
                )
                Text(
                    modifier = Modifier.semantics {
                        contentDescription = "Ambient workout ${metric.label.lowercase()}: ${metric.value}"
                    },
                    text = metric.value,
                    color = Color.White,
                    style = MaterialTheme.typography.numeralSmall.copy(fontWeight = FontWeight.Medium),
                    textAlign = TextAlign.Center,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
        }
    }
}

@Composable
private fun AmbientWorkoutTimeText(text: String) {
    Text(
        text = text,
        color = Color.White,
        style = MaterialTheme.typography.bodySmall,
        maxLines = 1
    )
}

private data class AmbientWorkoutOverlayModel(
    val phaseText: String,
    val exerciseName: String?,
    val metadataText: String?,
    val progressText: String?,
    val metrics: List<AmbientWorkoutMetric>
)

private data class AmbientWorkoutMetric(
    val label: String,
    val value: String
)

private fun ambientOverlayModel(
    workoutState: WorkoutState,
    exerciseName: String?,
    metadataText: String?,
    progressText: String?,
    formatWeightForState: (Double, java.util.UUID?) -> String
): AmbientWorkoutOverlayModel {
    return AmbientWorkoutOverlayModel(
        phaseText = ambientPhaseText(workoutState),
        exerciseName = exerciseName ?: ambientPhaseText(workoutState),
        metadataText = metadataText,
        progressText = progressText,
        metrics = ambientMetrics(workoutState, formatWeightForState)
    )
}

private fun ambientMetrics(
    workoutState: WorkoutState,
    formatWeightForState: (Double, java.util.UUID?) -> String
): List<AmbientWorkoutMetric> {
    return when (workoutState) {
        is WorkoutState.Set -> {
            when (val setData = workoutState.currentSetData) {
                is WeightSetData -> listOf(
                    AmbientWorkoutMetric(
                        label = "WEIGHT (KG)",
                        value = formatWeightForState(setData.getWeight(), workoutState.equipmentId)
                    ),
                    AmbientWorkoutMetric(label = "REPS", value = setData.actualReps.toString())
                )
                is BodyWeightSetData -> listOf(
                    AmbientWorkoutMetric(
                        label = "WEIGHT (KG)",
                        value = if (setData.additionalWeight == 0.0) {
                            "BW"
                        } else {
                            formatWeightForState(setData.additionalWeight, workoutState.equipmentId)
                        }
                    ),
                    AmbientWorkoutMetric(label = "REPS", value = setData.actualReps.toString())
                )
                is TimedDurationSetData -> listOf(
                    AmbientWorkoutMetric(
                        label = "TIMER",
                        value = formatWorkoutDurationSecondsForDisplay((setData.endTimer / 1000).coerceAtLeast(0))
                    )
                )
                is EnduranceSetData -> listOf(
                    AmbientWorkoutMetric(
                        label = "TIMER",
                        value = formatWorkoutDurationSecondsForDisplay((setData.endTimer / 1000).coerceAtLeast(0))
                    )
                )
                else -> listOf(AmbientWorkoutMetric(label = "SET", value = (workoutState.setIndex.toInt() + 1).toString()))
            }
        }
        is WorkoutState.Rest -> {
            val restData = workoutState.currentSetData as? RestSetData
            listOf(
                AmbientWorkoutMetric(
                    label = "TIMER",
                    value = formatWorkoutDurationSecondsForDisplay((restData?.endTimer ?: 0).coerceAtLeast(0))
                )
            )
        }
        is WorkoutState.CalibrationLoadSelection -> listOf(AmbientWorkoutMetric(label = "LOAD", value = "Pick"))
        is WorkoutState.CalibrationRIRSelection -> listOf(AmbientWorkoutMetric(label = "RIR", value = "Log"))
        is WorkoutState.AutoRegulationRIRSelection -> listOf(AmbientWorkoutMetric(label = "RIR", value = "Log"))
        is WorkoutState.Preparing -> listOf(AmbientWorkoutMetric(label = "STATUS", value = "Ready"))
        is WorkoutState.Completed -> listOf(AmbientWorkoutMetric(label = "STATUS", value = "Done"))
    }
}

private fun ambientPhaseText(workoutState: WorkoutState): String =
    when (workoutState) {
        is WorkoutState.Preparing -> "Preparing"
        is WorkoutState.Set -> "Set"
        is WorkoutState.Rest -> "Rest"
        is WorkoutState.Completed -> "Complete"
        is WorkoutState.CalibrationLoadSelection -> "Pick load"
        is WorkoutState.CalibrationRIRSelection -> "Log RIR"
        is WorkoutState.AutoRegulationRIRSelection -> "Log RIR"
    }

private fun ambientDetailText(workoutState: WorkoutState): String? =
    when (workoutState) {
        is WorkoutState.Set -> {
            val timerText = when (val setData = workoutState.currentSetData) {
                is TimedDurationSetData -> "Timer ${formatWorkoutDurationSecondsForDisplay(setData.startTimer / 1000)}"
                is EnduranceSetData -> "Timer --"
                else -> null
            }
            buildString {
                append("Set ${workoutState.setIndex.toInt() + 1}")
                if (!timerText.isNullOrBlank()) {
                    append(" ")
                    append(timerText)
                }
            }
        }
        is WorkoutState.Rest -> {
            "Timer --"
        }
        is WorkoutState.CalibrationLoadSelection -> "Calibration"
        is WorkoutState.CalibrationRIRSelection -> "Calibration"
        is WorkoutState.AutoRegulationRIRSelection -> "Auto-regulation"
        else -> null
    }

@Preview(
    name = "Ambient Workout Overlay",
    group = "WorkoutScreen/Ambient",
    device = WearDevices.LARGE_ROUND,
    showBackground = true
)
@Composable
private fun AmbientWorkoutOverlayPreview() {
    MyWorkoutAssistantTheme {
        AmbientWorkoutOverlayContent(
            ambientState = AmbientState.Ambient(
                burnInProtectionRequired = true,
                updateTimeMillis = 60_000L
            ),
            model = AmbientWorkoutOverlayModel(
                phaseText = "Set",
                exerciseName = "Incline Dumbbell Press",
                metadataText = "Set 2/4",
                progressText = "4/18",
                metrics = listOf(
                    AmbientWorkoutMetric(label = "WEIGHT (KG)", value = "80"),
                    AmbientWorkoutMetric(label = "REPS", value = "8")
                )
            ),
            timeContent = {
                AmbientWorkoutTimeText("21:42")
            }
        )
    }
}
