package com.gabstra.myworkoutassistant.screens

import android.content.Context
import android.Manifest
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.EnterTransition
import androidx.compose.animation.ExitTransition
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.AccessTimeFilled
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.edit
import androidx.lifecycle.viewmodel.compose.viewModel
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.HapticsViewModel
import com.gabstra.myworkoutassistant.composables.AppCircularLoadingIndicator
import com.gabstra.myworkoutassistant.heart_rate.ExternalHeartRateController
import com.gabstra.myworkoutassistant.heart_rate.ExternalHeartRateConnectionState
import com.gabstra.myworkoutassistant.heart_rate.PolarHeartRateViewModel
import com.gabstra.myworkoutassistant.heart_rate.WhoopHeartRateViewModel
import com.gabstra.myworkoutassistant.heart_rate.hasBluetoothPermission
import com.gabstra.myworkoutassistant.shared.HeartRateSource
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import com.gabstra.myworkoutassistant.workout.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.workout.CalibrationLoadScreen
import com.gabstra.myworkoutassistant.workout.AutoRegulationRIRScreen
import com.gabstra.myworkoutassistant.workout.CalibrationRIRScreen
import com.gabstra.myworkoutassistant.workout.ExerciseScreen
import com.gabstra.myworkoutassistant.workout.KeepOn
import com.gabstra.myworkoutassistant.workout.HeartRateLinearChart
import com.gabstra.myworkoutassistant.workout.WorkoutDisplayPreferences
import com.gabstra.myworkoutassistant.workout.LoadingText
import com.gabstra.myworkoutassistant.workout.RestScreen
import com.gabstra.myworkoutassistant.workout.TimeViewer
import com.gabstra.myworkoutassistant.workout.WorkoutCompleteScreen
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.delay

@Composable
private fun MobileRestTimerHeader(
    state: WorkoutState.Rest,
    viewModel: WorkoutViewModel,
    modifier: Modifier = Modifier,
) {
    val timerUiState by viewModel.workoutTimerService
        .timerUiState(state.set.id)
        .collectAsState(initial = null)
    val restSetData = state.currentSetData as? RestSetData
    val seconds = timerUiState?.displaySeconds ?: restSetData?.endTimer ?: 0

    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            modifier = Modifier.size(20.dp),
            imageVector = Icons.Filled.AccessTimeFilled,
            contentDescription = "Rest timer",
            tint = MaterialTheme.colorScheme.onBackground,
        )
        androidx.compose.foundation.layout.Spacer(modifier = Modifier.size(8.dp))
        TimeViewer(
            seconds = seconds.coerceAtLeast(0),
            style = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.SemiBold),
            color = MaterialTheme.colorScheme.onBackground,
        )
    }
}

@Composable
private fun MobileSetTimerHeader(
    state: WorkoutState.Set,
    viewModel: WorkoutViewModel,
    modifier: Modifier = Modifier,
) {
    val timerUiState by viewModel.workoutTimerService
        .timerUiState(state.set.id)
        .collectAsState(initial = null)
    val fallbackSeconds = when (val setData = state.currentSetData) {
        is TimedDurationSetData -> setData.endTimer / 1000
        is EnduranceSetData -> setData.endTimer / 1000
        else -> 0
    }
    val seconds = timerUiState?.displaySeconds ?: fallbackSeconds

    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            modifier = Modifier.size(20.dp),
            imageVector = Icons.Filled.AccessTimeFilled,
            contentDescription = "Set timer",
            tint = MaterialTheme.colorScheme.onBackground,
        )
        androidx.compose.foundation.layout.Spacer(modifier = Modifier.size(8.dp))
        TimeViewer(
            seconds = seconds.coerceAtLeast(0),
            style = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.SemiBold),
            color = MaterialTheme.colorScheme.onBackground,
        )
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
@Composable
fun WorkoutScreen(
    appViewModel: AppViewModel,
    workoutViewModel: WorkoutViewModel,
    hapticsViewModel: HapticsViewModel
)
{
    val context = LocalContext.current
    val screenState by workoutViewModel.screenState.collectAsState()
    val workoutState = screenState.workoutState
    val selectedWorkout = screenState.selectedWorkout
    val isPaused = screenState.isPaused
    val isSessionHydrationInFlight by workoutViewModel.isSessionHydrationInFlightFlow.collectAsState()
    val polarHeartRateViewModel: PolarHeartRateViewModel = viewModel()
    val whoopHeartRateViewModel: WhoopHeartRateViewModel = viewModel()
    val externalHeartRateController: ExternalHeartRateController? = when (selectedWorkout.heartRateSource) {
        HeartRateSource.POLAR_BLE -> polarHeartRateViewModel
        HeartRateSource.WHOOP_BLE -> whoopHeartRateViewModel
        HeartRateSource.WATCH_SENSOR -> null
    }
    val externalHeartRate by (
        externalHeartRateController?.heartRate?.collectAsState()
            ?: remember { mutableStateOf<Int?>(null) }
        )
    val externalConnectionState by (
        externalHeartRateController?.connectionState?.collectAsState()
            ?: remember { mutableStateOf<ExternalHeartRateConnectionState>(ExternalHeartRateConnectionState.Idle) }
        )
    var externalHeartRateSkipped by remember(selectedWorkout.id) { mutableStateOf(false) }
    val bluetoothPermissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions(),
    ) { permissions ->
        if (!externalHeartRateSkipped &&
            permissions[Manifest.permission.BLUETOOTH_SCAN] == true &&
            permissions[Manifest.permission.BLUETOOTH_CONNECT] == true
        ) {
            externalHeartRateController?.connect()
        }
    }

    LaunchedEffect(
        selectedWorkout.id,
        selectedWorkout.heartRateSource,
        externalHeartRateController,
        externalHeartRateSkipped,
    ) {
        val controller = externalHeartRateController ?: return@LaunchedEffect
        if (externalHeartRateSkipped) return@LaunchedEffect
        controller.initialize(
            context = context,
            config = workoutViewModel.getExternalHeartRateConfig(selectedWorkout.heartRateSource),
        )
        if (hasBluetoothPermission(context)) {
            controller.connect()
        } else {
            bluetoothPermissionLauncher.launch(
                arrayOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT),
            )
        }
    }

    DisposableEffect(externalHeartRateController) {
        onDispose { externalHeartRateController?.disconnect() }
    }

    LaunchedEffect(externalHeartRateController, externalHeartRateSkipped) {
        val controller = externalHeartRateController ?: return@LaunchedEffect
        if (externalHeartRateSkipped) return@LaunchedEffect
        while (true) {
            workoutViewModel.registerHeartBeat(controller.heartRate.value ?: 0)
            delay(1000)
        }
    }

    var showWorkoutInProgressDialog by remember { mutableStateOf(false) }
    val isCustomDialogOpen = screenState.isCustomDialogOpen
    var isWorkoutNameMarqueeEnabled by remember(selectedWorkout.id) { mutableStateOf(false) }
    val restSetId = (workoutState as? WorkoutState.Rest)?.set?.id
    var isRestTimerPageVisible by remember(restSetId) { mutableStateOf(true) }
    val activeSetId = (workoutState as? WorkoutState.Set)?.set?.id
    var isExerciseDetailPageVisible by remember(activeSetId) { mutableStateOf(true) }

    BackHandler(true) {
        if (isCustomDialogOpen || showWorkoutInProgressDialog) return@BackHandler

        showWorkoutInProgressDialog = true
        workoutViewModel.pauseWorkout()
        workoutViewModel.lightScreenUp()
    }

    val enableDimming = screenState.enableDimming
    val dimmedScreenBrightness by workoutViewModel.dimmedScreenBrightness
    LaunchedEffect(workoutViewModel) {
        workoutViewModel.setDimmedScreenBrightness(
            WorkoutDisplayPreferences.getDimmedScreenBrightness(context)
        )
    }
    KeepOn(
        appViewModel = workoutViewModel,
        enableDimming = enableDimming,
        dimmedScreenBrightness = dimmedScreenBrightness,
    ) {
        BoxWithConstraints(
            modifier = Modifier
                .fillMaxSize()
                .statusBarsPadding()
                .navigationBarsPadding(),
        ) {
            val contentHorizontalPadding = if (maxWidth >= 600.dp) 16.dp else 8.dp
            Column(modifier = Modifier.fillMaxSize()) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(52.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    IconButton(
                        modifier = Modifier.size(52.dp),
                        onClick = {
                            if (!isCustomDialogOpen) {
                                showWorkoutInProgressDialog = true
                                workoutViewModel.pauseWorkout()
                                workoutViewModel.lightScreenUp()
                            }
                        },
                    ) {
                        Icon(
                            imageVector = Icons.Default.Close,
                            contentDescription = "Leave workout",
                            tint = MaterialTheme.colorScheme.onBackground,
                        )
                    }
                    val restState = workoutState as? WorkoutState.Rest
                    val setState = workoutState as? WorkoutState.Set
                    val isTimedSet = setState?.currentSetData?.let { setData ->
                        setData is TimedDurationSetData || setData is EnduranceSetData
                    } == true
                    if (restState != null && !isRestTimerPageVisible) {
                        MobileRestTimerHeader(
                            modifier = Modifier.weight(1f),
                            state = restState,
                            viewModel = workoutViewModel,
                        )
                    } else if (setState != null && isTimedSet && !isExerciseDetailPageVisible) {
                        MobileSetTimerHeader(
                            modifier = Modifier.weight(1f),
                            state = setState,
                            viewModel = workoutViewModel,
                        )
                    } else {
                        Text(
                            text = selectedWorkout.name,
                            modifier = Modifier
                                .weight(1f)
                                .padding(horizontal = 8.dp)
                                .then(
                                    if (isWorkoutNameMarqueeEnabled) {
                                        Modifier.basicMarquee(iterations = Int.MAX_VALUE)
                                    } else {
                                        Modifier
                                    }
                                )
                                .clickable {
                                    isWorkoutNameMarqueeEnabled = !isWorkoutNameMarqueeEnabled
                                    hapticsViewModel.doGentleVibration()
                                },
                            style = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.SemiBold),
                            color = MaterialTheme.colorScheme.onBackground,
                            textAlign = TextAlign.Center,
                            maxLines = 1,
                            softWrap = false,
                            overflow = if (isWorkoutNameMarqueeEnabled) {
                                TextOverflow.Clip
                            } else {
                                TextOverflow.Ellipsis
                            },
                        )
                    }
                    Box(modifier = Modifier.size(52.dp))
                }
            val stateTypeKey = remember(workoutState) {
                when (workoutState) {
                    is WorkoutState.Preparing -> "Preparing"
                    is WorkoutState.Set -> "Set"
                    is WorkoutState.Rest -> "Rest"
                    is WorkoutState.Completed -> "Completed"
                    is WorkoutState.CalibrationLoadSelection -> "CalibrationLoadSelection"
                    is WorkoutState.CalibrationRIRSelection -> "CalibrationRIRSelection"
                    is WorkoutState.AutoRegulationRIRSelection -> "AutoRegulationRIRSelection"
                }
            }

            @Suppress("UnusedContentLambdaTargetStateParameter")
            AnimatedContent(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .padding(horizontal = contentHorizontalPadding)
                    .padding(top = 12.dp, bottom = 4.dp),
                targetState = stateTypeKey to workoutState,
                contentKey = { (typeKey, _) -> typeKey },
                transitionSpec = {
                    EnterTransition.None togetherWith ExitTransition.None
                }, label = "",
                contentAlignment = Alignment.Center
            ) { (_, animatedWorkoutState) ->
                when (val state = animatedWorkoutState) {
                    is WorkoutState.CalibrationLoadSelection -> {
                        CalibrationLoadScreen(
                            viewModel = workoutViewModel,
                            hapticsViewModel = hapticsViewModel,
                            state = state
                        )
                    }
                    is WorkoutState.CalibrationRIRSelection -> {
                        CalibrationRIRScreen(
                            viewModel = workoutViewModel,
                            hapticsViewModel = hapticsViewModel,
                            state = state
                        )
                    }
                    is WorkoutState.AutoRegulationRIRSelection -> {
                        AutoRegulationRIRScreen(
                            viewModel = workoutViewModel,
                            hapticsViewModel = hapticsViewModel,
                            state = state
                        )
                    }
                    is WorkoutState.Preparing -> {
                        var currentMillis by remember { mutableIntStateOf(0) }
                        var hasTriggeredNextState by remember { mutableStateOf(false) }
                        val isExternalHeartRateRequired = externalHeartRateController != null &&
                            !externalHeartRateSkipped
                        val isExternalHeartRateReady =
                            externalConnectionState is ExternalHeartRateConnectionState.Streaming
                        val canSkipExternalHeartRate = isExternalHeartRateRequired &&
                            !isExternalHeartRateReady &&
                            (currentMillis >= 30_000 ||
                                externalConnectionState is ExternalHeartRateConnectionState.Error)

                        LaunchedEffect(Unit) {
                            while (true) {
                                delay(1000)
                                currentMillis += 1000
                            }
                        }

                        LaunchedEffect(
                            state,
                            state.dataLoaded,
                            currentMillis,
                            isPaused,
                            showWorkoutInProgressDialog,
                            screenState.hasWorkoutRecord,
                            isSessionHydrationInFlight,
                            isExternalHeartRateRequired,
                            isExternalHeartRateReady,
                        ) {
                            if (hasTriggeredNextState) {
                                return@LaunchedEffect
                            }

                            val isReady = state.dataLoaded &&
                                currentMillis >= 3000 &&
                                (!isExternalHeartRateRequired || isExternalHeartRateReady) &&
                                !isSessionHydrationInFlight

                            // Check if workout was explicitly started before auto-progressing
                            val prefs = context.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
                            val isWorkoutInProgress = prefs.getBoolean("isWorkoutInProgress", false)

                            // The baseline workout record is created by setWorkoutStart(), so its
                            // absence cannot be used as a prerequisite for starting the session.
                            if (isReady && isWorkoutInProgress && !isPaused && !showWorkoutInProgressDialog) {
                                if (!workoutViewModel.isCurrentPreparingState(state)) {
                                    hasTriggeredNextState = true
                                    return@LaunchedEffect
                                }
                                hasTriggeredNextState = true

                                workoutViewModel.lightScreenUp()
                                if (screenState.hasWorkoutRecord) {
                                    workoutViewModel.finishPreparedResume()
                                } else {
                                    workoutViewModel.setWorkoutStart()
                                }
                            }
                        }

                        Box(
                            modifier = Modifier
                                .fillMaxSize(),
                            contentAlignment = Alignment.Center
                        ) {
                            if (!isExternalHeartRateRequired) {
                                Column(
                                    horizontalAlignment = Alignment.CenterHorizontally,
                                    verticalArrangement = Arrangement.spacedBy(16.dp),
                                ) {
                                    AppCircularLoadingIndicator()
                                    Text(
                                        text = "Starting workout",
                                        style = MaterialTheme.typography.titleLarge,
                                        textAlign = TextAlign.Center,
                                    )
                                }
                            } else {
                                Column(
                                    horizontalAlignment = Alignment.CenterHorizontally,
                                    verticalArrangement = Arrangement.spacedBy(16.dp),
                                ) {
                                    AppCircularLoadingIndicator()
                                    Text(
                                        text = "Getting your ${selectedWorkout.heartRateSource.displayName()} ready",
                                        style = MaterialTheme.typography.titleLarge,
                                        textAlign = TextAlign.Center,
                                    )
                                    Text(
                                        text = when (val connection = externalConnectionState) {
                                            ExternalHeartRateConnectionState.Idle ->
                                                "Preparing connection"
                                            is ExternalHeartRateConnectionState.Connecting ->
                                                connection.message
                                            is ExternalHeartRateConnectionState.Streaming ->
                                                "Streaming from ${connection.deviceLabel}"
                                            is ExternalHeartRateConnectionState.Error ->
                                                connection.message
                                        },
                                        style = MaterialTheme.typography.bodyLarge,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        textAlign = TextAlign.Center,
                                    )
                                    if (canSkipExternalHeartRate) {
                                        Button(
                                            onClick = {
                                                externalHeartRateSkipped = true
                                                externalHeartRateController.disconnect()
                                                hapticsViewModel.doGentleVibration()
                                            },
                                        ) {
                                            Text("Skip")
                                        }
                                    }
                                }
                            }
                        }
                    }

                    is WorkoutState.Set -> {
                        ExerciseScreen(
                            workoutViewModel,
                            hapticsViewModel,
                            state,
                            hearthRateChart = {
                                if (externalHeartRateController != null && !externalHeartRateSkipped) {
                                    HeartRateLinearChart(
                                        heartRate = externalHeartRate ?: 0,
                                        age = screenState.userAge,
                                        measuredMaxHeartRate = screenState.measuredMaxHeartRate,
                                        restingHeartRate = screenState.restingHeartRate,
                                        lowerBoundMaxHRPercent = state.lowerBoundMaxHRPercent,
                                        upperBoundMaxHRPercent = state.upperBoundMaxHRPercent,
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .padding(horizontal = 16.dp, vertical = 8.dp),
                                    )
                                }
                            },
                            onLeaveWorkout = {
                                showWorkoutInProgressDialog = true
                                workoutViewModel.pauseWorkout()
                                workoutViewModel.lightScreenUp()
                            },
                            onExerciseDetailPageVisibilityChanged = { isVisible ->
                                isExerciseDetailPageVisible = isVisible
                            },
                        )
                    }

                    is WorkoutState.Rest -> {
                        RestScreen(
                            workoutViewModel,
                            hapticsViewModel,
                            state,
                            { },
                            onTimerEnd = {
                                workoutViewModel.storeSetData()
                                workoutViewModel.pushAndStoreWorkoutData(false, context) {
                                    workoutViewModel.goToNextState()
                                    workoutViewModel.lightScreenUp()
                                }
                            },
                            onLeaveWorkout = {
                                showWorkoutInProgressDialog = true
                                workoutViewModel.pauseWorkout()
                                workoutViewModel.lightScreenUp()
                            },
                            onRestTimerPageVisibilityChanged = { isVisible ->
                                isRestTimerPageVisible = isVisible
                            },
                        )
                    }

                    is WorkoutState.Completed -> {
                        WorkoutCompleteScreen(
                            appViewModel,
                            workoutViewModel,
                            state,
                            hapticsViewModel
                        )
                    }
                }
            }
            }
        }
        CustomDialogYesOnLongPress(
            show = showWorkoutInProgressDialog,
            title = "Workout in progress",
            handleYesClick = {
                hapticsViewModel.doGentleVibration()

                val prefs = context.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
                prefs.edit { putBoolean("isWorkoutInProgress", false) }

                appViewModel.goBack()
                appViewModel.triggerUpdate()

                showWorkoutInProgressDialog = false
            },
            handleNoClick = {
                hapticsViewModel.doGentleVibration()
                showWorkoutInProgressDialog = false
                workoutViewModel.resumeWorkout()
            },
            closeTimerInMillis = 5000,
            handleOnAutomaticClose = {
                showWorkoutInProgressDialog = false
                workoutViewModel.resumeWorkout()
            },
            holdTimeInMillis = 1000,
            onVisibilityChange = { isVisible ->
                if (isVisible) {
                    workoutViewModel.setDimming(false)
                } else {
                    workoutViewModel.reEvaluateDimmingForCurrentState()
                }
            }
        )
    }
}
