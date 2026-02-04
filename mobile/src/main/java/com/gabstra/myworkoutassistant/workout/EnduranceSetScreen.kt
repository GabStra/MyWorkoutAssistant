package com.gabstra.myworkoutassistant.workout

import android.os.SystemClock
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
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
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight.Companion.W700
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutTimerService
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.time.Duration
import java.time.LocalDateTime


@OptIn(ExperimentalFoundationApi::class)
@Composable
fun EnduranceSetScreen (
    viewModel: WorkoutViewModel,
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
    val scope = rememberCoroutineScope()

    DisposableEffect(state.set.id) {
        onDispose {
            // Unregister timer when composable is disposed
            viewModel.workoutTimerService.unregisterTimer(state.set.id)
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
    val headerStyle = MaterialTheme.typography.bodySmall
    val itemStyle = remember(typography) { typography.bodySmall.copy(fontWeight = W700) }

    LaunchedEffect(isTimerInEditMode) {
        while (isTimerInEditMode) {
            if (SystemClock.elapsedRealtime() - lastInteractionTime > 2000) {
                isTimerInEditMode = false
            }
            delay(1000)
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
        if(exercise.showCountDownTimer){
            displayStartingDialog = true
            delay(500)
            hapticsViewModel.doHardVibration()
            delay(1000)
            countdownValue = 2
            hapticsViewModel.doHardVibration()
            delay(1000)
            countdownValue = 1
            hapticsViewModel.doHardVibration()
            delay(1000)
            displayStartingDialog = false
            hapticsViewModel.doHardVibrationTwice()
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
                color = if (overLimit) MaterialTheme.colorScheme.secondary else if (isDifferent) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onBackground,
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
                color = if (isOverLimit) MaterialTheme.colorScheme.secondary else if (isDifferent) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onBackground,
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
        if (state.startTime != null) {
            // Timer has started - ensure it's registered with service
            // Don't check for completion here - let WorkoutTimerService handle it
            if (!isPaused && !viewModel.workoutTimerService.isTimerRegistered(set.id)) {
                // Timer should be running - register if not already registered
                startTimer()
            }
            return@LaunchedEffect
        }

        if (set.autoStart && !isPaused) {
            delay(500)

            showCountDownIfEnabled()

            if (state.startTime == null) {
                state.startTime = LocalDateTime.now()
            }

            hapticsViewModel.doHardVibrationTwice()
            startTimer()
        }
    }

    @Composable
    fun SetScreen(customModifier: Modifier) {
        Column (
            modifier = customModifier,
        ){
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(5.dp)
            ) {
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(2.5.dp)
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
                }
                if (showStartButton) {
                    IconButton(
                        modifier = Modifier.size(35.dp),
                        onClick = {
                            scope.launch {
                                showCountDownIfEnabled()

                                if(state.startTime == null){
                                    state.startTime = LocalDateTime.now()
                                }

                                hapticsViewModel.doHardVibrationTwice()
                                startTimer()

                                showStartButton = false
                            }
                        },
                        colors = IconButtonDefaults.iconButtonColors(containerColor = MaterialTheme.colorScheme.secondary),
                    ) {
                        Icon(
                            imageVector = Icons.Default.PlayArrow,
                            contentDescription = "Start",
                            tint = MaterialTheme.colorScheme.onBackground
                        )
                    }
                }else{
                    IconButton(
                        modifier = Modifier.size(35.dp).alpha(if(viewModel.workoutTimerService.isTimerRegistered(set.id)) 1f else 0f),
                        onClick = {
                            hapticsViewModel.doGentleVibration()
                            viewModel.workoutTimerService.unregisterTimer(set.id)
                            showStopDialog = true
                        },
                        colors = IconButtonDefaults.iconButtonColors(containerColor = MaterialTheme.colorScheme.error),
                    ) {
                        Icon(
                            imageVector = Icons.Default.Stop,
                            contentDescription = "Stop",
                            tint = MaterialTheme.colorScheme.onBackground
                        )
                    }
                }
            }
        }
    }

    customComponentWrapper {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
            modifier = modifier
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
                    content = {
                        textComposable()
                    }
                )
            } else {
                Column(
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(5.dp)
                ) {
                    exerciseTitleComposable()
                    if (extraInfo != null) {
                        //HorizontalDivider(modifier = Modifier.fillMaxWidth(), thickness = 1.dp)
                        extraInfo(state)
                    }
                    SetScreen(customModifier = Modifier)
                }
            }
        }

        CustomDialogYesOnLongPress(
            show = showStopDialog,
            title = "Stop Exercise",
            message = "Do you want to stop this exercise?",
            handleYesClick = {
                hapticsViewModel.doGentleVibration()
                onTimerDisabled()
                onTimerEnd()
                showStopDialog = false
            },
            handleNoClick = {
                hapticsViewModel.doGentleVibration()
                showStopDialog = false
                startTimer()
            },
            handleOnAutomaticClose = {},
            holdTimeInMillis = 1000,
            onVisibilityChange = { isVisible ->
                if (isVisible) {
                    viewModel.setDimming(false)
                } else {
                    viewModel.reEvaluateDimmingForCurrentState()
                }
            }
        )

        CountDownDialog(displayStartingDialog,countdownValue)
    }
}

