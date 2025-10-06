package com.gabstra.myworkoutassistant.composables

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
import androidx.wear.compose.material3.Icon
import androidx.wear.compose.material3.IconButton
import androidx.wear.compose.material3.IconButtonDefaults
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.LightGray
import com.gabstra.myworkoutassistant.shared.Red
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.time.LocalDateTime


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
    val scope = rememberCoroutineScope()
    var timerJob by remember { mutableStateOf<Job?>(null) }

    DisposableEffect(Unit) {
        onDispose {
            timerJob?.cancel()
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

    val previousSet = state.previousSetData as EnduranceSetData
    var currentSet by remember(set.id) { mutableStateOf(state.currentSetData as EnduranceSetData) }

    var isTimerInEditMode by remember { mutableStateOf(false) }


    var lastInteractionTime by remember { mutableLongStateOf(SystemClock.elapsedRealtime()) }
    val updateInteractionTime = { lastInteractionTime = SystemClock.elapsedRealtime() }

    val typography = MaterialTheme.typography
    val headerStyle = MaterialTheme.typography.labelSmall
    val itemStyle = remember(typography) { typography.numeralMedium.copy(fontWeight = W700) }

    LaunchedEffect(isTimerInEditMode) {
        while (isTimerInEditMode) {
            if (SystemClock.elapsedRealtime() - lastInteractionTime > 2000) {
                isTimerInEditMode = false
            }
            delay(1000)
        }
    }

    LaunchedEffect(currentSet) {
        state.currentSetData = currentSet
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

    val textComposable = @Composable {
        val isDifferent = currentSet.startTimer != previousSet.startTimer

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Center
        ){
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
                                currentSet = currentSet.copy(
                                    startTimer = previousSet.startTimer
                                )

                                hapticsViewModel.doHardVibrationTwice()
                            }
                        }
                    ),
                seconds = (if(isTimerInEditMode) currentSet.startTimer else currentMillis) / 1000,
                style = itemStyle,
                color = if(isOverLimit) Green else if(isDifferent) MaterialTheme.colorScheme.primary else LightGray,
            )
        }
    }

    fun startTimerJob() {
        timerJob?.cancel()
        timerJob = scope.launch {
            onTimerEnabled()

            var finishedNaturally = false
            var nextExecutionTime = ((SystemClock.elapsedRealtime() / 1000) + 1) * 1000 // round UP

            while (isActive) {
                val now = SystemClock.elapsedRealtime()
                val waitTime = (nextExecutionTime - now).coerceAtLeast(0)
                delay(waitTime)

                if (!isActive) break // cooperative cancel after delay

                // tick
                currentMillis += 1000
                currentSet = currentSet.copy(endTimer = currentMillis)

                if (!isOverLimit && currentMillis >= currentSet.startTimer) {
                    hapticsViewModel.doHardVibrationTwice()
                    if (set.autoStop) {
                        finishedNaturally = true
                        break
                    } else {
                        isOverLimit = true
                    }
                }

                nextExecutionTime += 1000
            }

            if (finishedNaturally) {
                state.currentSetData = currentSet.copy(endTimer = currentSet.startTimer)
                onTimerDisabled()
                onTimerEnd()
            }
        }

        if (!hasBeenStartedOnce) hasBeenStartedOnce = true
    }

    val isPaused by viewModel.isPaused

    LaunchedEffect(set.id, set.autoStart, isPaused) {
        val startedAt = state.startTime
        if (startedAt != null) {
            // Elapsed since start
            val now = LocalDateTime.now()
            val elapsedMillis = java.time.Duration.between(startedAt, now).toMillis()
                .toInt().coerceAtLeast(0)

            currentMillis = elapsedMillis

            if (currentMillis >= currentSet.startTimer) {
                isOverLimit = !set.autoStop
                if (set.autoStop) {
                    state.currentSetData = currentSet.copy(endTimer = currentSet.startTimer)
                    onTimerDisabled()
                    onTimerEnd()
                    return@LaunchedEffect
                }
            }

            if (!isPaused && timerJob?.isActive != true) {
                startTimerJob()
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
            if (timerJob?.isActive != true) {
                startTimerJob()
            }
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
                        text = "TIME",
                        style = headerStyle,
                        textAlign = TextAlign.Center,
                    )
                    textComposable()
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
                                startTimerJob()

                                showStartButton = false
                            }
                        },
                        colors = IconButtonDefaults.iconButtonColors(containerColor = Green),
                    ){
                        Icon(imageVector = Icons.Default.PlayArrow, contentDescription = "Start")
                    }
                }else{
                    IconButton(
                        modifier = Modifier.size(35.dp).alpha(if(timerJob?.isActive == true) 1f else 0f),
                        onClick = {
                            hapticsViewModel.doGentleVibration()
                            timerJob?.cancel()
                            showStopDialog = true
                        },
                        colors = IconButtonDefaults.iconButtonColors(containerColor = Red, contentColor = LightGray),
                    ) {
                        Icon(imageVector = Icons.Default.Stop, contentDescription = "Stop")
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
                    modifier = Modifier.fillMaxSize(),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(5.dp)
                ) {
                    exerciseTitleComposable()
                    if (extraInfo != null) {
                        //HorizontalDivider(modifier = Modifier.fillMaxWidth(), thickness = 1.dp)
                        extraInfo(state)
                    }
                    SetScreen(customModifier = Modifier.weight(1f))
                }
            }
        }

        CustomDialogYesOnLongPress(
            show = showStopDialog,
            title = "Stop Exercise",
            message = "Do you want to stop this exercise?",
            handleYesClick = {
                hapticsViewModel.doGentleVibration()
                state.currentSetData = currentSet.copy(
                    endTimer = currentMillis
                )

                onTimerDisabled()
                onTimerEnd()
                showStopDialog = false
            },
            handleNoClick = {
                hapticsViewModel.doGentleVibration()
                showStopDialog = false
                startTimerJob()
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