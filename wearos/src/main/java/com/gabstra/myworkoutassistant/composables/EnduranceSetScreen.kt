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
import androidx.compose.foundation.layout.padding
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
import com.gabstra.myworkoutassistant.composables.rememberWearCoroutineScope
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
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutTimerService
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.time.Duration
import java.time.LocalDateTime
import java.time.temporal.ChronoUnit


@OptIn(ExperimentalFoundationApi::class)
@Composable
fun EnduranceSetScreen (
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    modifier: Modifier,
    state: WorkoutState.Set,
    onTimerEnd: () -> Unit,
    onTimerEnabled : () -> Unit,
    onTimerDisabled: () -> Unit,
    extraInfo: (@Composable (WorkoutState.Set) -> Unit)? = null,
    exerciseTitleComposable:  @Composable () -> Unit,
    customComponentWrapper: @Composable (@Composable () -> Unit) -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberWearCoroutineScope()
    var autoStartJob by remember(state.set.id) { mutableStateOf<Job?>(null) }

    DisposableEffect(state.set.id) {
        onDispose {
            // Clean up auto-start job when composable is disposed
            // Timer service continues running in background and will unregister when timer completes
            autoStartJob?.cancel()
        }
    }

    var hasBeenStartedOnce by remember { mutableStateOf(false) }

    var isOverLimit by remember { mutableStateOf(false) }

    val set = state.set as EnduranceSet

    val exercise = remember(state.exerciseId) {
        viewModel.exercisesById[state.exerciseId]!!
    }

    var displayStartingDialog by remember(set.id) { mutableStateOf(false) }
    var countdownValue by remember(set) { mutableIntStateOf(3) }
    var countdownInitiated by remember(set.id) { mutableStateOf(false) }

    var showStartButton by remember(set) { mutableStateOf(!set.autoStart) }

    val previousSetStartTimer = remember(state.previousSetData) {
        (state.previousSetData as? EnduranceSetData)?.startTimer
    }
    var currentSet by remember(set.id) {
        val setData = state.currentSetData as? EnduranceSetData
        mutableStateOf(setData ?: EnduranceSetData(0, 0, false, false))
    }

    var isTimerInEditMode by remember { mutableStateOf(false) }


    var lastInteractionTime by remember { mutableLongStateOf(SystemClock.elapsedRealtime()) }
    val updateInteractionTime = { lastInteractionTime = SystemClock.elapsedRealtime() }

    val typography = MaterialTheme.typography
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

    LaunchedEffect(currentSet.startTimer) {
        val setData = state.currentSetData as? EnduranceSetData ?: return@LaunchedEffect
        if (setData.startTimer != currentSet.startTimer) {
            state.currentSetData = setData.copy(startTimer = currentSet.startTimer)
        }
    }

    var currentMillis by remember(set.id) { mutableIntStateOf(0) }
    var showStopDialog by remember { mutableStateOf(false) }


    suspend fun showCountDownIfEnabled(){
        if(!exercise.showCountDownTimer) return
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
            countdownValue = 3
        }
    }

    fun onMinusClick(){
        if (currentSet.startTimer > 5000){
            currentSet = currentSet.copy(startTimer = currentSet.startTimer - 5000)
            hapticsViewModel.doGentleVibration()
        }
        updateInteractionTime()
    }

    fun onPlusClick(){
        currentSet = currentSet.copy(startTimer = currentSet.startTimer + 5000)
        hapticsViewModel.doGentleVibration()
        updateInteractionTime()
    }

    @Composable
    fun EnduranceRunningDisplay(initialMillis: Int) {
        val setData = state.currentSetData as? EnduranceSetData
        val displayMillis = setData?.endTimer ?: initialMillis
        val previousTimer = previousSetStartTimer ?: (setData?.startTimer ?: initialMillis)
        val isDifferent = displayMillis != previousTimer
        val overLimit = setData != null && displayMillis >= setData.startTimer && !set.autoStop
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Center
        ) {
            TimeViewer(
                modifier = Modifier.combinedClickable(
                    onClick = {},
                    onLongClick = {
                        if (showStartButton) {
                            isTimerInEditMode = !isTimerInEditMode
                            updateInteractionTime()
                            hapticsViewModel.doGentleVibration()
                        }
                    },
                    onDoubleClick = {}
                ),
                seconds = displayMillis / 1000,
                style = itemStyle,
                color = if (overLimit) Green else if (isDifferent) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onBackground,
            )
        }
    }

    val textComposable = @Composable {
        val previousTimer = previousSetStartTimer ?: currentSet.startTimer
        val isDifferent = currentSet.startTimer != previousTimer
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Center
        ) {
            TimeViewer(
                modifier = Modifier.combinedClickable(
                    onClick = {},
                    onLongClick = {
                        if (showStartButton) {
                            isTimerInEditMode = !isTimerInEditMode
                            updateInteractionTime()
                            hapticsViewModel.doGentleVibration()
                        }
                    },
                    onDoubleClick = {
                        if (isTimerInEditMode) {
                            currentSet = currentSet.copy(startTimer = previousTimer)
                            hapticsViewModel.doHardVibrationTwice()
                        }
                    }
                ),
                seconds = (if (isTimerInEditMode) currentSet.startTimer else currentMillis) / 1000,
                style = itemStyle,
                color = if (isOverLimit) Green else if (isDifferent) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onBackground,
            )
        }
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

        if (!hasBeenStartedOnce) hasBeenStartedOnce = true
    }

    val isPaused by viewModel.isPaused

    LaunchedEffect(set.id, set.autoStart, isPaused) {
        // Check if timer has already started (e.g., resuming workout)
        // Note: state.startTime check is inside the effect, not a dependency, to prevent
        // double-triggering when state.startTime changes from null to a value
        if (state.startTime != null) {
            // Timer has started - ensure it's registered with service
            // Don't check for completion here - let WorkoutTimerService handle it
            if (!isPaused && !viewModel.workoutTimerService.isTimerRegistered(set.id)) {
                // Timer should be running - register if not already registered
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

        if (autoStartJob?.isActive != true) {
            autoStartJob = scope.launch {
                delay(500)
                showCountDownIfEnabled()

                if (state.startTime == null) {
                    state.startTime = LocalDateTime.now()
                }

                hapticsViewModel.doHardVibrationTwice()
                startTimer()
            }
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
                EnduranceRunningDisplay(initialMillis = 0)
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
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
            modifier = modifier.semantics {
                contentDescription = SetValueSemantics.EnduranceSetTypeDescription
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
                onTimerDisabled()
                onTimerEnd()
            },
            handleNoClick = {
                hapticsViewModel.doGentleVibration()
                showStopDialog = false
                startTimer()
            },
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
