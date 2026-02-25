package com.gabstra.myworkoutassistant.composables


import android.os.SystemClock
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Stop
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.Icon
import androidx.wear.compose.material3.IconButton
import androidx.wear.compose.material3.IconButtonDefaults
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.Red
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workout.timer.WorkoutTimerService
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.time.LocalDateTime


@OptIn(ExperimentalFoundationApi::class)
@Composable
fun TimedDurationSetScreen(
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    modifier: Modifier,
    state: WorkoutState.Set,
    onTimerEnd: () -> Unit,
    onTimerEnabled: () -> Unit,
    onTimerDisabled: () -> Unit,
    extraInfo: (@Composable (WorkoutState.Set) -> Unit)? = null,
    exerciseTitleComposable: @Composable () -> Unit,
    customComponentWrapper: @Composable (@Composable () -> Unit) -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberWearCoroutineScope()
    var autoStartJob by remember(state.set.id) { mutableStateOf<Job?>(null) }
    val topOverlayController = LocalTopOverlayController.current

    DisposableEffect(state.set.id) {
        onDispose {
            // Clean up auto-start job when composable is disposed
            // Timer service continues running in background and will unregister when timer completes
            autoStartJob?.cancel()
            topOverlayController.clear("timed_duration_countdown_${state.set.id}")
        }
    }

    val set = state.set as TimedDurationSet

    val exercise = remember(state.exerciseId) {
        viewModel.exercisesById[state.exerciseId]!!
    }

    val restoredTimedData = state.currentSetData as? TimedDurationSetData
    val hasRecoveredProgress = restoredTimedData != null &&
        restoredTimedData.endTimer > 0 &&
        restoredTimedData.endTimer < restoredTimedData.startTimer
    var showStartButton by remember(set.id) {
        mutableStateOf(!set.autoStart && state.startTime == null && !hasRecoveredProgress)
    }

    var hasBeenStartedOnce by remember { mutableStateOf(false) }

    var displayStartingDialog by remember(set.id) { mutableStateOf(false) }
    var countdownValue by remember(set.id) { mutableIntStateOf(3) }
    var countdownInitiated by remember(set.id) { mutableStateOf(false) }
    var hasAutoStartBeenInitiated by remember(set.id) { mutableStateOf(false) }

    val previousSetStartTimer = remember(state.previousSetData) {
        (state.previousSetData as? TimedDurationSetData)?.startTimer
    }
    var currentSet by remember(set.id) {
        val setData = state.currentSetData as? TimedDurationSetData
        mutableStateOf(setData ?: TimedDurationSetData(0, 0, false, false))
    }

    val isPaused by viewModel.isPaused
    val timerEditModeController = remember(set.id) {
        ServiceBackedTimerEditModeController(
            isWorkoutPaused = { isPaused },
            isTimerRegistered = { viewModel.workoutTimerService.isTimerRegistered(set.id) },
            readProgressMillis = {
                (state.currentSetData as? TimedDurationSetData)?.endTimer ?: currentSet.startTimer
            },
            readMaxMillis = {
                (state.currentSetData as? TimedDurationSetData)?.startTimer ?: currentSet.startTimer
            },
            isProgressRunning = { progressMillis, _ -> progressMillis > 0 },
            toElapsedMillis = { progressMillis, maxMillis -> (maxMillis - progressMillis).coerceAtLeast(0) },
            applyFrozenProgressMillis = { progressMillis ->
                val setData = state.currentSetData as? TimedDurationSetData
                if (setData != null) {
                    state.currentSetData = setData.copy(endTimer = progressMillis)
                }
            },
            applyStartTimeFromElapsedMillis = { elapsedMillis ->
                state.startTime = LocalDateTime.now().minusNanos(elapsedMillis.toLong() * 1_000_000L)
            },
            registerTimer = {
                viewModel.workoutTimerService.registerTimer(
                    state = state,
                    callbacks = WorkoutTimerService.TimerCallbacks(
                        onTimerEnd = {
                            hapticsViewModel.doHardVibrationTwice()
                            onTimerEnd()
                        },
                        onTimerEnabled = onTimerEnabled,
                        onTimerDisabled = onTimerDisabled
                    )
                )
            },
            unregisterTimer = { viewModel.workoutTimerService.unregisterTimer(set.id) },
            nowMillis = { SystemClock.elapsedRealtime() }
        )
    }
    val isTimerInEditMode = timerEditModeController.isEditMode
    val updateInteractionTime = { timerEditModeController.recordInteraction() }

    val headerStyle = MaterialTheme.typography.bodyExtraSmall
    val itemStyle =  MaterialTheme.typography.numeralSmall

    LaunchedEffect(isTimerInEditMode) {
        while (isTimerInEditMode) {
            if (timerEditModeController.shouldAutoClose(timeoutMillis = 5000L)) {
                timerEditModeController.updateEditMode(false)
            }
            delay(1000) // Check every second
        }
    }

    LaunchedEffect(currentSet.startTimer) {
        val setData = state.currentSetData as? TimedDurationSetData ?: return@LaunchedEffect
        if (setData.startTimer != currentSet.startTimer) {
            state.currentSetData = setData.copy(startTimer = currentSet.startTimer)
        }
    }

    var currentMillis by remember(set.id) { mutableIntStateOf(currentSet.startTimer) }
    var showStopDialog by remember { mutableStateOf(false) }


    suspend fun showCountDownIfEnabled() {
        if (!exercise.showCountDownTimer) return
        // Prevent multiple simultaneous countdowns
        if (displayStartingDialog || countdownInitiated) return

        // Set guard flags first to prevent race conditions
        countdownInitiated = true
        displayStartingDialog = true
        // Ensure countdownValue is set to 3 after dialog is shown to prevent brief flash
        countdownValue = 3
        try {
            delay(500)
            hapticsViewModel.doHardVibration()
            delay(1000)
            countdownValue = 2
            hapticsViewModel.doHardVibration()
            delay(1000)
            countdownValue = 1
            hapticsViewModel.doHardVibration()
            delay(1000)
            hapticsViewModel.doHardVibrationTwice()
        } finally {
            displayStartingDialog = false
            countdownInitiated = false
        }
    }

    LaunchedEffect(displayStartingDialog) {
        if (displayStartingDialog) {
            viewModel.setDimming(false)
        } else {
            viewModel.reEvaluateDimmingForCurrentState()
        }
    }

    LaunchedEffect(displayStartingDialog, countdownValue, state.set.id) {
        val owner = "timed_duration_countdown_${state.set.id}"
        if (displayStartingDialog) {
            topOverlayController.show(owner = owner) {
                CountdownOverlayBox(
                    show = true,
                    time = countdownValue
                )
            }
        } else {
            topOverlayController.clear(owner)
        }
    }

    fun onMinusClick() {
        if (currentSet.startTimer > 5000) {
            val newTimerValue = currentSet.startTimer - 5000
            currentSet = currentSet.copy(startTimer = newTimerValue)
            currentMillis = newTimerValue
            hapticsViewModel.doGentleVibration()
        }
        updateInteractionTime()
    }

    fun onPlusClick() {
        val newTimerValue = currentSet.startTimer + 5000
        currentSet = currentSet.copy(startTimer = newTimerValue)
        currentMillis = newTimerValue
        hapticsViewModel.doGentleVibration()
        updateInteractionTime()
    }

    fun startTimer() {
        // Ensure startTime is set
        if (state.startTime == null) {
            state.startTime = LocalDateTime.now()
        }
        
        // Register timer with service - it will handle updates
        viewModel.workoutTimerService.registerTimer(
            state = state,
            callbacks = WorkoutTimerService.TimerCallbacks(
                onTimerEnd = {
                    hapticsViewModel.doHardVibrationTwice()
                    onTimerEnd()
                },
                onTimerEnabled = onTimerEnabled,
                onTimerDisabled = onTimerDisabled
            )
        )

        if (!hasBeenStartedOnce) {
            hasBeenStartedOnce = true
        }
    }

    LaunchedEffect(set.id, set.autoStart, isPaused) {
        // Check if timer has already started (e.g., resuming workout)
        // Note: state.startTime check is inside the effect, not a dependency, to prevent
        // double-triggering when state.startTime changes from null to a value
        if (state.startTime != null) {
            // Re-anchor once after recovery so resumed value matches what user last saw
            // before process death, even if recovery navigation took time.
            viewModel.applyPostRecoveryTimerReanchorIfNeeded()
            // Timer has started - ensure it's registered with service
            // Don't check for completion here - let WorkoutTimerService handle it
            if (!isPaused && !viewModel.workoutTimerService.isTimerRegistered(set.id)) {
                // Timer should be running - register if not already registered
                // This handles Bug 5: Timer Service Not Re-registered on Resume
                android.util.Log.d("TimedDurationSetScreen", "Re-registering timer on resume: setId=${set.id}, startTime=${state.startTime}")
                startTimer()
            }
            autoStartJob?.cancel()
            return@LaunchedEffect
        }

        val recoveredSetData = state.currentSetData as? TimedDurationSetData
        val hasRecoverableProgress = recoveredSetData != null &&
            recoveredSetData.endTimer > 0 &&
            recoveredSetData.endTimer < recoveredSetData.startTimer
        if (hasRecoverableProgress) {
            val elapsedMillis = (recoveredSetData.startTimer - recoveredSetData.endTimer).coerceAtLeast(0)
            state.startTime = LocalDateTime.now().minusNanos(elapsedMillis.toLong() * 1_000_000L)
            showStartButton = false
            if (!isPaused && !viewModel.workoutTimerService.isTimerRegistered(set.id)) {
                startTimer()
            }
            autoStartJob?.cancel()
            return@LaunchedEffect
        }

        if (!set.autoStart) {
            autoStartJob?.cancel()
            return@LaunchedEffect
        }

        if (isPaused) {
            autoStartJob?.cancel()
            return@LaunchedEffect
        }

        // Prevent duplicate auto-start initiation
        if (hasAutoStartBeenInitiated) {
            return@LaunchedEffect
        }

        if (autoStartJob?.isActive != true) {
            // Set flag immediately before any async operations to prevent race conditions
            hasAutoStartBeenInitiated = true
            autoStartJob = scope.launch {
                delay(500)
                showCountDownIfEnabled()

                state.startTime = LocalDateTime.now()
                hapticsViewModel.doHardVibrationTwice()
                startTimer()
            }
        }
    }

    @Composable
    fun TimedDurationRunningDisplay(initialMillis: Int) {
        val setData = state.currentSetData as? TimedDurationSetData
        val displayMillis = setData?.endTimer ?: initialMillis
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Center
        ) {
            TimeViewer(
                modifier = Modifier
                    .combinedClickable(
                        onClick = {},
                        onLongClick = {
                            if (showStartButton) {
                                timerEditModeController.toggleEditMode()
                                updateInteractionTime()
                                hapticsViewModel.doGentleVibration()
                            }
                        },
                        onDoubleClick = {}
                    )
                    .semantics { contentDescription = SetValueSemantics.TimedDurationValueDescription },
                seconds = displayMillis / 1000,
                style = itemStyle,
                color = MaterialTheme.colorScheme.onBackground
            )
        }
    }

    val textComposable = @Composable {
        val previousTimer = previousSetStartTimer ?: currentSet.startTimer
        val isDifferent = currentSet.startTimer != previousTimer
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Center
        ) {
            TimeViewer(
                modifier = Modifier
                    .combinedClickable(
                        onClick = {},
                        onLongClick = {
                            if (showStartButton) {
                                timerEditModeController.toggleEditMode()
                                updateInteractionTime()
                                hapticsViewModel.doGentleVibration()
                            }
                        },
                        onDoubleClick = {
                            if (isTimerInEditMode) {
                                val newTimerValue = previousTimer
                                currentSet = currentSet.copy(startTimer = newTimerValue)
                                currentMillis = newTimerValue
                                hapticsViewModel.doHardVibrationTwice()
                            }
                        }
                    )
                    .semantics { contentDescription = SetValueSemantics.TimedDurationValueDescription },
                seconds = currentMillis / 1000,
                style = itemStyle,
                color = if (isDifferent) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onBackground
            )
        }
    }

    @Composable
    fun SetScreen(customModifier: Modifier) {
        Column(
            modifier = customModifier,
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(2.5.dp, alignment = Alignment.Top)
        ) {
            Text(
                text = "TIMER",
                style = headerStyle,
                textAlign = TextAlign.Center,
            )
            if (isTimerInEditMode) {
                textComposable()
            } else {
                TimedDurationRunningDisplay(initialMillis = currentSet.startTimer)
            }

            if (showStartButton) {
                IconButton(
                    modifier = Modifier.size(50.dp),
                    onClick = {
                        autoStartJob?.cancel()
                        scope.launch {
                            showCountDownIfEnabled()

                            if (state.startTime == null) {
                                state.startTime = LocalDateTime.now()
                            }

                            hapticsViewModel.doHardVibrationTwice()
                            startTimer()

                            showStartButton = false
                            autoStartJob?.cancel()
                        }
                    },
                    colors = IconButtonDefaults.iconButtonColors(containerColor = Green),
                ) {
                    Icon(
                        modifier = Modifier.size(30.dp),
                        imageVector = Icons.Default.PlayArrow,
                        contentDescription = "Start",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }

            if (viewModel.workoutTimerService.isTimerRegistered(set.id)) {
                IconButton(
                    modifier = Modifier.size(50.dp),
                    onClick = {
                        hapticsViewModel.doGentleVibration()
                        viewModel.workoutTimerService.unregisterTimer(set.id)
                        showStopDialog = true
                    },
                    colors = IconButtonDefaults.iconButtonColors(containerColor = Red),
                ) {
                    Icon(
                        modifier = Modifier.size(30.dp),
                        imageVector = Icons.Default.Stop,
                        contentDescription = "Stop",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        }
    }

    customComponentWrapper {
        Box(
            modifier = modifier
                .fillMaxSize()
                .semantics {
                contentDescription = SetValueSemantics.TimedDurationSetTypeDescription
            }
        ) {
            if (isTimerInEditMode) {
                ControlButtonsVertical(
                    modifier = Modifier
                        .fillMaxSize()
                        .clickable(
                            interactionSource = null,
                            indication = null
                        ) {
                            updateInteractionTime()
                        },
                    onMinusTap = { onMinusClick() },
                    onMinusLongPress = { onMinusClick() },
                    onPlusTap = { onPlusClick() },
                    onPlusLongPress = { onPlusClick() },
                    onCloseClick = {
                        timerEditModeController.updateEditMode(false)
                    },
                    content = {
                        textComposable()
                    }
                )
            } else {
                Column(
                    modifier = Modifier.fillMaxSize(),
                    horizontalAlignment = Alignment.CenterHorizontally,

                ) {
                    Column(
                        verticalArrangement = Arrangement.spacedBy(5.dp)
                    ) {
                        exerciseTitleComposable()
                        if (extraInfo != null) {
                            //HorizontalDivider(modifier = Modifier.fillMaxWidth(), thickness = 1.dp)
                            extraInfo(state)
                        }
                    }
                    Spacer(modifier = Modifier.height(10.dp))
                    SetScreen(customModifier = Modifier)
                }
            }
        }

        CustomDialogYesOnLongPress(
            show = showStopDialog,
            title = "Stop Exercise",
            message = "Do you want to proceed?",
            handleYesClick = {
                hapticsViewModel.doGentleVibration()
                onTimerDisabled()
                onTimerEnd()
            },
            handleNoClick = {
                hapticsViewModel.doGentleVibration()
                showStopDialog = false
                startTimer()
            },
            closeTimerInMillis = 5000,
            handleOnAutomaticClose = {},
            onVisibilityChange = { isVisible ->
                if (isVisible) {
                    viewModel.setDimming(false)
                } else {
                    viewModel.reEvaluateDimmingForCurrentState()
                }
            }
        )

    }
}
