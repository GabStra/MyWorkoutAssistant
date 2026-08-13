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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.HapticsViewModel
import com.gabstra.myworkoutassistant.composables.TimedSetExecutionLoadLabel
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import com.gabstra.myworkoutassistant.shared.workout.timer.WorkoutTimerService
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.time.Duration
import java.time.LocalDateTime


@OptIn(ExperimentalFoundationApi::class)
@Composable
fun TimedDurationSetScreen(
    viewModel: WorkoutViewModel,
    hapticsViewModel: HapticsViewModel,
    modifier: Modifier,
    state: WorkoutState.Set,
    onTimerEnd: () -> Unit,
    onTimerEnabled : () -> Unit,
    onTimerDisabled: () -> Unit,
    extraInfo: (@Composable (WorkoutState.Set) -> Unit)? = null,
    exerciseTitleComposable:  @Composable () -> Unit,
    heartRateChart: @Composable () -> Unit = {},
    customComponentWrapper: @Composable (@Composable () -> Unit) -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    val set = state.set as TimedDurationSet

    val exercise = remember(state.exerciseId) {
        viewModel.exercisesById[state.exerciseId]!!
    }
    val equipment = remember(state.equipmentId) { state.equipmentId?.let(viewModel::getEquipmentById) }

    var showStartButton by remember(set.id) {
        mutableStateOf(!set.autoStart && state.startTime == null && !state.hasBeenExecuted)
    }
    var showRepeatButton by remember(set.id) { mutableStateOf(state.hasBeenExecuted) }

    var hasBeenStartedOnce by remember { mutableStateOf(false) }

    var displayStartingDialog by  remember(set.id) { mutableStateOf(false) }
    var countdownValue by remember(set) { mutableIntStateOf(3) }

    val previousSetStartTimer = remember(state.previousSetData) {
        (state.previousSetData as? TimedDurationSetData)?.startTimer
    }
    val comparisonSetStartTimer = remember(state.historicalSetData, previousSetStartTimer) {
        (state.historicalSetData as? TimedDurationSetData)?.startTimer ?: previousSetStartTimer
    }
    var currentSet by remember(set.id) {
        val setData = state.currentSetData as? TimedDurationSetData
        mutableStateOf(setData ?: TimedDurationSetData(0, 0, false, false))
    }
    val initialStartTimer = (state.previousSetData as? TimedDurationSetData)?.startTimer
        ?: currentSet.startTimer
    var currentMillis by remember(set.id) { mutableIntStateOf(currentSet.startTimer) }

    fun markSetExecuted() {
        val setData = state.currentSetData as? TimedDurationSetData ?: return
        state.currentSetData = setData.copy(hasBeenExecuted = true)
        state.hasBeenExecuted = true
    }

    fun prepareSetRepeat() {
        val setData = state.currentSetData as? TimedDurationSetData ?: return
        val resetData = setData.copy(
            endTimer = setData.startTimer,
            hasBeenExecuted = false
        )
        state.currentSetData = resetData
        state.hasBeenExecuted = false
        state.startTime = null
        currentSet = resetData
        currentMillis = resetData.startTimer
    }

    var isTimerInEditMode by remember { mutableStateOf(false) }

    var lastInteractionTime by remember { mutableLongStateOf(SystemClock.elapsedRealtime()) }
    val updateInteractionTime = { lastInteractionTime = SystemClock.elapsedRealtime() }

    val typography = MaterialTheme.typography
    val headerStyle = MaterialTheme.typography.titleMedium
    val itemStyle = remember(typography) { typography.displayLarge }

    LaunchedEffect(isTimerInEditMode) {
        while (isTimerInEditMode) {
            if (SystemClock.elapsedRealtime() - lastInteractionTime >= CONTROL_EDIT_INACTIVITY_TIMEOUT_MILLIS) {
                isTimerInEditMode = false
            }
            delay(1000)
        }
    }

    LaunchedEffect(currentSet.startTimer) {
        val setData = state.currentSetData as? TimedDurationSetData ?: return@LaunchedEffect
        if (setData.startTimer != currentSet.startTimer) {
            state.currentSetData = setData.copy(startTimer = currentSet.startTimer)
        }
    }

    // Local display value for edit mode only; running timer reads from state in TimedDurationRunningDisplay
    var showStopDialog by remember { mutableStateOf(false) }

    suspend fun showCountDownIfEnabled(){
        if (!exercise.showCountDownTimer) return

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
        }
    }

    fun onMinusClick(){
        if (currentSet.startTimer > 5_000){
            val newTimerValue = currentSet.startTimer - TIMER_EDIT_INCREMENT_MILLIS
            currentSet = currentSet.copy(startTimer = newTimerValue)
            currentMillis = newTimerValue
            hapticsViewModel.doGentleVibration()
        }
        updateInteractionTime()
    }

    fun onPlusClick(){
        val newTimerValue = currentSet.startTimer + TIMER_EDIT_INCREMENT_MILLIS
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
                    markSetExecuted()
                    hapticsViewModel.doHardVibrationTwiceWithBeep()
                    onTimerEnd()
                },
                onTimerEnabled = onTimerEnabled,
                onTimerDisabled = onTimerDisabled
            )
        )

        if(!hasBeenStartedOnce){
            hasBeenStartedOnce = true
        }
    }

    val isPaused by viewModel.isPaused

    LaunchedEffect(set.id, set.autoStart, isPaused, state.startTime) {
        if (state.hasBeenExecuted && !viewModel.workoutTimerService.isTimerRegistered(set.id)) {
            showStartButton = false
            showRepeatButton = true
            return@LaunchedEffect
        }
        // Check if timer has already started (e.g., resuming workout)
        if (state.startTime != null) {
            showStartButton = false
            showRepeatButton = false
            // Timer has started - ensure it's registered with service
            // Don't check for completion here - let WorkoutTimerService handle it
            if (!isPaused && !viewModel.workoutTimerService.isTimerRegistered(set.id)) {
                // Timer should be running - register if not already registered
                // This handles Bug 5: Timer Service Not Re-registered on Resume
                android.util.Log.d("TimedDurationSetScreen", "Re-registering timer on resume: setId=${set.id}, startTime=${state.startTime}")
                startTimer()
            }
            return@LaunchedEffect
        }

        if (set.autoStart && !isPaused) {
            delay(500)
            showCountDownIfEnabled()
            state.startTime = LocalDateTime.now()
            hapticsViewModel.doHardVibrationTwice()
            startTimer()
        }
    }

    @Composable
    fun TimedDurationRunningDisplay(
        initialMillis: Int,
        onLongClick: () -> Unit,
        onDoubleClick: () -> Unit,
    ) {
        val setData = state.currentSetData as? TimedDurationSetData
        val displayMillis = setData?.endTimer ?: initialMillis
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp),
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
                        onLongClick()
                    },
                    onDoubleClick = onDoubleClick
                ),
                seconds = displayMillis / 1000,
                style = itemStyle,
                color = MaterialTheme.colorScheme.onBackground
            )
        }
    }

    val textComposable = @Composable {
        val previousTimer = comparisonSetStartTimer ?: currentSet.startTimer
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp),
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
                            val newTimerValue = previousTimer
                            currentSet = currentSet.copy(startTimer = newTimerValue)
                            currentMillis = newTimerValue
                            hapticsViewModel.doHardVibrationTwice()
                        }
                    }
                ),
                seconds = currentMillis / 1000,
                style = itemStyle,
                color = MaterialTheme.colorScheme.onBackground
            )
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
                        TimedDurationRunningDisplay(
                            initialMillis = currentSet.startTimer,
                            onLongClick = {},
                            onDoubleClick = {}
                        )
                    }
                }
                if (showStartButton || showRepeatButton) {
                    IconButton(
                        modifier = Modifier.size(70.dp),
                        onClick = {
                            scope.launch {
                                if (showRepeatButton) {
                                    prepareSetRepeat()
                                }
                                showCountDownIfEnabled()

                                if(state.startTime == null){
                                    state.startTime = LocalDateTime.now()
                                }

                                hapticsViewModel.doHardVibrationTwice()
                                startTimer()

                                showStartButton = false
                                showRepeatButton = false
                            }
                        },
                        colors = IconButtonDefaults.iconButtonColors(containerColor = MaterialTheme.colorScheme.secondary),
                    ) {
                        Icon(
                            modifier = Modifier.size(35.dp),
                            imageVector = Icons.Default.PlayArrow,
                            contentDescription = if (showRepeatButton) "Repeat set" else "Start",
                            tint = MaterialTheme.colorScheme.onBackground
                        )
                    }
                }else{
                    IconButton(
                        modifier = Modifier.size(70.dp).alpha(if(viewModel.workoutTimerService.isTimerRegistered(set.id)) 1f else 0f),
                        onClick = {
                            hapticsViewModel.doGentleVibration()
                            viewModel.workoutTimerService.unregisterTimer(set.id)
                            showStopDialog = true
                        },
                        colors = IconButtonDefaults.iconButtonColors(containerColor = MaterialTheme.colorScheme.error),
                    ) {
                        Icon(
                            modifier = Modifier.size(35.dp),
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
                    isResetEnabled = currentSet.startTimer != initialStartTimer,
                    onCloseClick = { isTimerInEditMode = false },
                    onResetClick = {
                        currentSet = currentSet.copy(startTimer = initialStartTimer)
                        currentMillis = initialStartTimer
                        updateInteractionTime()
                        hapticsViewModel.doGentleVibration()
                    },
                    content = {
                        SetValueSection(label = "TIMER", headerStyle = headerStyle) {
                            textComposable()
                        }
                    }
                )
            } else {
                Column(
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    exerciseTitleComposable()
                    TimedSetExecutionLoadLabel(
                        equipment = equipment,
                        selectedWeight = currentSet.actualWeight,
                        editable = !set.autoStart && state.startTime == null && !state.hasBeenExecuted,
                        onWeightSelected = { selectedWeight ->
                            currentSet = currentSet.copy(actualWeight = selectedWeight)
                            state.currentSetData = currentSet
                        },
                    )
                    if (extraInfo != null) {
                        //HorizontalDivider(modifier = Modifier.fillMaxWidth(), thickness = 1.dp)
                        extraInfo(state)
                    }
                    SetScreen(customModifier = Modifier)
                    heartRateChart()
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
                markSetExecuted()
                onTimerEnd()
                showStopDialog = false
            },
            handleNoClick = {
                hapticsViewModel.doGentleVibration()
                showStopDialog = false
                startTimer()
            },
            closeTimerInMillis = 5000,
            handleOnAutomaticClose = {
                showStopDialog = false
                startTimer()
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

        CountdownOverlayBox(displayStartingDialog, countdownValue)
    }
}


