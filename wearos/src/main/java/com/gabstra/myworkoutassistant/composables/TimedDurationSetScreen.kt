package com.gabstra.myworkoutassistant.composables


import android.os.SystemClock
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
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
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutTimerService
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.time.Duration
import java.time.LocalDateTime
import java.time.temporal.ChronoUnit


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
    val scope = rememberCoroutineScope()
    var autoStartJob by remember(state.set.id) { mutableStateOf<Job?>(null) }

    DisposableEffect(state.set.id) {
        onDispose {
            // Unregister timer when composable is disposed
            viewModel.workoutTimerService.unregisterTimer(state.set.id)
            autoStartJob?.cancel()
        }
    }

    val set = state.set as TimedDurationSet

    val exercise = remember(state.exerciseId) {
        viewModel.exercisesById[state.exerciseId]!!
    }

    var showStartButton by remember(set.id) { mutableStateOf(!set.autoStart) }

    var hasBeenStartedOnce by remember { mutableStateOf(false) }

    var displayStartingDialog by remember(set.id) { mutableStateOf(false) }
    var countdownValue by remember(set) { mutableIntStateOf(3) }
    var countdownInitiated by remember(set.id) { mutableStateOf(false) }

    val previousSet = state.previousSetData as TimedDurationSetData
    var currentSet by remember(set.id) { mutableStateOf(state.currentSetData as TimedDurationSetData) }

    var isTimerInEditMode by remember { mutableStateOf(false) }

    var lastInteractionTime by remember { mutableLongStateOf(SystemClock.elapsedRealtime()) }
    val updateInteractionTime = { lastInteractionTime = SystemClock.elapsedRealtime() }

    val headerStyle = MaterialTheme.typography.bodyExtraSmall
    val itemStyle =  MaterialTheme.typography.numeralSmall

    LaunchedEffect(isTimerInEditMode) {
        while (isTimerInEditMode) {
            if (System.currentTimeMillis() - lastInteractionTime > 5000) {
                isTimerInEditMode = false
            }
            delay(1000) // Check every second
        }
    }

    LaunchedEffect(currentSet) {
        state.currentSetData = currentSet
    }

    // Sync currentMillis with state.currentSetData.endTimer for UI display
    // The timer service updates state.currentSetData.endTimer, so we read from it
    var currentMillis by remember { mutableIntStateOf((state.currentSetData as TimedDurationSetData).endTimer) }
    
    // Update currentMillis when state changes (from timer service or local edits)
    LaunchedEffect(state.currentSetData) {
        val setData = state.currentSetData as? TimedDurationSetData ?: return@LaunchedEffect
        currentMillis = setData.endTimer
    }
    var showStopDialog by remember { mutableStateOf(false) }


    suspend fun showCountDownIfEnabled() {
        if (!exercise.showCountDownTimer) return
        // Prevent multiple simultaneous countdowns
        if (displayStartingDialog || countdownInitiated) return

        countdownInitiated = true
        countdownValue = 3
        displayStartingDialog = true
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
            countdownValue = 3
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

    val isPaused by viewModel.isPaused

    LaunchedEffect(set.id, set.autoStart, isPaused, state.startTime) {
        if (state.startTime != null) {
            // Timer has started - ensure it's registered with service
            val now = LocalDateTime.now()
            val elapsedMillis = java.time.Duration.between(state.startTime, now).toMillis()
            val remainingMillis = maxOf(currentSet.startTimer - elapsedMillis.toInt(), 0)
            
            if (remainingMillis > 0 && !isPaused) {
                // Timer should be running - register if not already registered
                if (!viewModel.workoutTimerService.isTimerRegistered(set.id)) {
                    startTimer()
                }
            } else if (remainingMillis <= 0) {
                // Timer already completed
                state.currentSetData = currentSet.copy(endTimer = 0)
                viewModel.workoutTimerService.unregisterTimer(set.id)
                hapticsViewModel.doHardVibrationTwice()
                onTimerDisabled()
                onTimerEnd()
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

        if (autoStartJob?.isActive != true) {
            autoStartJob = scope.launch {
                delay(500)
                showCountDownIfEnabled()

                state.startTime = LocalDateTime.now()
                hapticsViewModel.doHardVibrationTwice()
                startTimer()
            }
        }
    }

    val textComposable = @Composable {
        val isDifferent = currentSet.startTimer != previousSet.startTimer

        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Center
        ) {
            TimeViewer(
                modifier = Modifier
                    .combinedClickable(
                        onClick = {
                        },
                        onLongClick = {
                            if (showStartButton) {
                                isTimerInEditMode = !isTimerInEditMode
                                updateInteractionTime()
                                hapticsViewModel.doGentleVibration()
                            }
                        },
                        onDoubleClick = {
                            if (isTimerInEditMode) {
                                val newTimerValue = previousSet.startTimer
                                currentSet = currentSet.copy(startTimer = newTimerValue)
                                currentMillis = newTimerValue
                                hapticsViewModel.doHardVibrationTwice()
                            }
                        }
                    )
                    .semantics {
                        contentDescription = SetValueSemantics.TimedDurationValueDescription
                    },
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
            textComposable()

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
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
            modifier = modifier.semantics {
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
                        isTimerInEditMode = false
                    },
                    content = {
                        textComposable()
                    }
                )
            } else {
                Column(
                    modifier = Modifier.fillMaxSize(),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    Column(
                        verticalArrangement = Arrangement.spacedBy(5.dp, Alignment.Bottom)
                    ) {
                        exerciseTitleComposable()
                        if (extraInfo != null) {
                            //HorizontalDivider(modifier = Modifier.fillMaxWidth(), thickness = 1.dp)
                            extraInfo(state)
                        }
                    }
                    Spacer(modifier = Modifier.height(5.dp))
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
                state.currentSetData = currentSet.copy(
                    endTimer = currentMillis
                )

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

        CountDownDialog(
            show = displayStartingDialog,
            time = countdownValue,
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
