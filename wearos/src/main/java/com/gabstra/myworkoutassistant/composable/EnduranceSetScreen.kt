package com.gabstra.myworkoutassistant.composable

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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.ButtonDefaults
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.FormatTime
import com.gabstra.myworkoutassistant.presentation.theme.MyColors
import com.gabstra.myworkoutassistant.shared.VibrateGentle
import com.gabstra.myworkoutassistant.shared.VibrateTwice
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.time.LocalDateTime

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun EnduranceSetScreen (
    viewModel: AppViewModel,
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

    var showStartButton by remember(set) { mutableStateOf(!set.autoStart) }

    val previousSet = state.previousSetData as EnduranceSetData
    var currentSet by remember(set.id) { mutableStateOf(state.currentSetData as EnduranceSetData) }

    var isTimerInEditMode by remember { mutableStateOf(false) }


    var lastInteractionTime by remember { mutableLongStateOf(System.currentTimeMillis()) }

    val updateInteractionTime = {
        lastInteractionTime = System.currentTimeMillis()
    }

    val typography = MaterialTheme.typography
    val headerStyle = remember(typography) { typography.body1.copy(fontSize = typography.body1.fontSize * 0.625f) }

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

    var currentMillis by remember(set.id) { mutableIntStateOf(0) }
    var showStopDialog by remember { mutableStateOf(false) }

    fun onMinusClick(){
        if (currentSet.startTimer > 5000){
            currentSet = currentSet.copy(startTimer = currentSet.startTimer - 5000)
            VibrateGentle(context)
        }
        updateInteractionTime()
    }

    fun onPlusClick(){
        currentSet = currentSet.copy(startTimer = currentSet.startTimer + 5000)
        VibrateGentle(context)
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
            ScalableText(
                modifier = Modifier
                    .fillMaxWidth()
                    .combinedClickable(
                    onClick = {
                    },
                    onLongClick = {
                        if (showStartButton) {
                            isTimerInEditMode = !isTimerInEditMode
                            updateInteractionTime()
                            VibrateGentle(context)
                        }
                    },
                    onDoubleClick = {
                        if (isTimerInEditMode) {
                            currentSet = currentSet.copy(
                                startTimer = previousSet.startTimer
                            )

                            VibrateTwice(context)
                        }
                    }
                ),
                color = if(isOverLimit) MyColors.Green else if(isDifferent) MyColors.Orange else MyColors.White,
                text = FormatTime((if(isTimerInEditMode) currentSet.startTimer else currentMillis) / 1000),
                style = MaterialTheme.typography.body1.copy(fontSize = typography.body1.fontSize * 1.625f,fontWeight = FontWeight.Bold),
            )
        }
    }

    fun startTimerJob() {
        timerJob?.cancel()
        timerJob = scope.launch {
            onTimerEnabled()

            var nextExecutionTime = System.currentTimeMillis() + 1000
            nextExecutionTime = (nextExecutionTime / 1000) * 1000 // Round to next second boundary

            while (true) {
                val currentTime = System.currentTimeMillis()
                val waitTime = maxOf(0, nextExecutionTime - currentTime)

                delay(waitTime) // Wait until next second boundary

                currentMillis += 1000

                currentSet = currentSet.copy(
                    endTimer = currentMillis
                )

                if (isOverLimit) {
                    nextExecutionTime += 1000 // Schedule next second
                    continue
                }

                if (currentMillis >= currentSet.startTimer) {
                    VibrateTwice(context)
                    if (set.autoStop) break
                    else isOverLimit = true
                }

                nextExecutionTime += 1000 // Schedule next second
            }

            state.currentSetData = currentSet.copy(
                endTimer = currentSet.startTimer
            )
            onTimerDisabled()
            onTimerEnd()
        }

        if (!hasBeenStartedOnce) {
            hasBeenStartedOnce = true
        }
    }

    val isPaused by viewModel.isPaused

    LaunchedEffect(isPaused) {
        if(!hasBeenStartedOnce){
            return@LaunchedEffect
        }

        if (isPaused) {
            timerJob?.takeIf { it.isActive }?.cancel()
        } else {
            if (timerJob?.isActive != true && !isTimerInEditMode) {
                startTimerJob()
            }
        }
    }

    LaunchedEffect(set) {
        if(state.startTime != null) {
            // Calculate elapsed time between startTime and now
            val now = LocalDateTime.now()
            val elapsedMillis = java.time.Duration.between(state.startTime, now).toMillis()

            currentMillis = elapsedMillis.toInt()

            if(currentMillis >= currentSet.startTimer) {
                isOverLimit = !set.autoStop

                if(set.autoStop) {
                    // If auto stop is enabled and we're already over time
                    state.currentSetData = currentSet.copy(
                        endTimer = currentSet.startTimer
                    )
                    onTimerDisabled()
                    onTimerEnd()
                }
            }

            startTimerJob()
            return@LaunchedEffect
        }

        if (set.autoStart) {
            delay(500)
            VibrateTwice(context)
            startTimerJob()

            if(state.startTime == null){
                state.startTime = LocalDateTime.now()
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
                        textAlign = TextAlign.Center
                    )
                    textComposable()
                }
                if (showStartButton) {
                    Button(
                        modifier = Modifier.size(35.dp),
                        onClick = {
                            VibrateGentle(context)
                            startTimerJob()
                            showStartButton = false

                            if(state.startTime == null){
                                state.startTime = LocalDateTime.now()
                            }
                        },
                        colors = ButtonDefaults.buttonColors(backgroundColor = MyColors.Green)
                    ) {
                        Icon(imageVector = Icons.Default.PlayArrow, contentDescription = "Start")
                    }
                }else{
                    Button(
                        modifier = Modifier.size(35.dp).alpha(if(timerJob?.isActive == true) 1f else 0f),
                        onClick = {
                            VibrateGentle(context)
                            timerJob?.cancel()
                            showStopDialog = true
                        },
                        colors = ButtonDefaults.buttonColors(backgroundColor = MaterialTheme.colors.error)
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

        LaunchedEffect(showStopDialog) {
            if(showStopDialog){
                viewModel.lightScreenPermanently()
            }else{
                viewModel.restoreScreenDimmingState()
            }
        }

        CustomDialogYesOnLongPress(
            show = showStopDialog,
            title = "Stop Exercise",
            message = "Do you want to stop this exercise?",
            handleYesClick = {
                VibrateGentle(context)
                state.currentSetData = currentSet.copy(
                    endTimer = currentMillis
                )

                onTimerDisabled()
                onTimerEnd()
                showStopDialog = false
            },
            handleNoClick = {
                VibrateGentle(context)
                showStopDialog = false
                startTimerJob()
            },
            handleOnAutomaticClose = {},
            holdTimeInMillis = 1000
        )
    }
}