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
import androidx.compose.ui.text.font.FontFamily
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
import com.gabstra.myworkoutassistant.shared.Red
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
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
    var timerJob by remember { mutableStateOf<Job?>(null) }

    DisposableEffect(Unit) {
        onDispose {
            timerJob?.cancel()
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

    val previousSet = state.previousSetData as TimedDurationSetData
    var currentSet by remember(set.id) { mutableStateOf(state.currentSetData as TimedDurationSetData) }

    var isTimerInEditMode by remember { mutableStateOf(false) }

    var lastInteractionTime by remember { mutableLongStateOf(SystemClock.elapsedRealtime()) }
    val updateInteractionTime = { lastInteractionTime = SystemClock.elapsedRealtime() }

    val typography = MaterialTheme.typography
    val headerStyle = MaterialTheme.typography.bodyExtraSmall
    val itemStyle = remember(typography) { typography.numeralSmall.copy(fontWeight = W700, fontFamily = FontFamily.Monospace) }

    LaunchedEffect(isTimerInEditMode) {
        while (isTimerInEditMode) {
            if (System.currentTimeMillis() - lastInteractionTime > 2000) {
                isTimerInEditMode = false
            }
            delay(1000) // Check every second
        }
    }

    LaunchedEffect(currentSet) {
        state.currentSetData = currentSet
    }

    var currentMillis by remember(set.id) { mutableIntStateOf(currentSet.startTimer) }
    var showStopDialog by remember { mutableStateOf(false) }


    suspend fun showCountDownIfEnabled() {
        if (exercise.showCountDownTimer) {
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

    fun startTimerJob() {
        timerJob?.cancel()
        timerJob = scope.launch {
            val now = LocalDateTime.now()
            val nextSecond = now.plusSeconds(1).truncatedTo(ChronoUnit.SECONDS)
            delay(java.time.Duration.between(now, nextSecond).toMillis())
            
            onTimerEnabled()

            while (currentMillis > 0) {
                val now = LocalDateTime.now()
                val nextSecond = now.plusSeconds(1).truncatedTo(ChronoUnit.SECONDS)
                delay(Duration.between(now, nextSecond).toMillis())

                currentMillis = (currentMillis - 1000).coerceAtLeast(0)
                currentSet = currentSet.copy(endTimer = currentMillis)
            }

            state.currentSetData = currentSet.copy(
                endTimer = 0
            )
            hapticsViewModel.doHardVibrationTwice()
            onTimerDisabled()
            onTimerEnd()
        }

        if (!hasBeenStartedOnce) {
            hasBeenStartedOnce = true
        }
    }

    val isPaused by viewModel.isPaused

    LaunchedEffect(set.id, set.autoStart, isPaused) {
        if (state.startTime != null) {
            val now = LocalDateTime.now()
            val elapsedMillis = java.time.Duration.between(state.startTime, now).toMillis()
            currentMillis = maxOf(currentSet.startTimer - elapsedMillis.toInt(), 0)
            if (currentMillis > 0 && !isPaused)
                startTimerJob()
            else if (currentMillis <= 0) {
                state.currentSetData = currentSet.copy(endTimer = 0)
                hapticsViewModel.doHardVibrationTwice()
                onTimerDisabled()
                onTimerEnd()
            }
            return@LaunchedEffect
        }

        if (set.autoStart && !isPaused) {
            delay(500)
            showCountDownIfEnabled()


            state.startTime = LocalDateTime.now()
            hapticsViewModel.doHardVibrationTwice()
            startTimerJob()
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
                    ),
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
                        scope.launch {
                            showCountDownIfEnabled()

                            if (state.startTime == null) {
                                state.startTime = LocalDateTime.now()
                            }

                            hapticsViewModel.doHardVibrationTwice()
                            startTimerJob()

                            showStartButton = false
                        }
                    },
                    colors = IconButtonDefaults.iconButtonColors(containerColor = Green),
                ) {
                    Icon(
                        modifier = Modifier.size(30.dp),
                        imageVector = Icons.Default.PlayArrow,
                        contentDescription = "Start",
                        tint = MaterialTheme.colorScheme.onSurface
                    )
                }
            }

            if (timerJob?.isActive == true) {
                IconButton(
                    modifier = Modifier.size(50.dp),
                    onClick = {
                        hapticsViewModel.doGentleVibration()
                        timerJob?.cancel()
                        showStopDialog = true
                    },
                    colors = IconButtonDefaults.iconButtonColors(containerColor = Red),
                ) {
                    Icon(
                        modifier = Modifier.size(30.dp),
                        imageVector = Icons.Default.Stop,
                        contentDescription = "Stop",
                        tint = MaterialTheme.colorScheme.onSurface
                    )
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
                    Column(
                        verticalArrangement = Arrangement.spacedBy(5.dp, Alignment.Bottom)
                    ) {
                        exerciseTitleComposable()
                        if (extraInfo != null) {
                            //HorizontalDivider(modifier = Modifier.fillMaxWidth(), thickness = 1.dp)
                            extraInfo(state)
                        }
                    }
                    SetScreen(customModifier = Modifier.weight(1f))
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
                showStopDialog = false
            },
            handleNoClick = {
                hapticsViewModel.doGentleVibration()
                showStopDialog = false
                startTimerJob()
            },
            closeTimerInMillis = 5000,
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

        CountDownDialog(displayStartingDialog, countdownValue)
    }
}