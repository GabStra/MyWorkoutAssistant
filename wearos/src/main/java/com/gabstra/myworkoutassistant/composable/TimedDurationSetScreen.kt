package com.gabstra.myworkoutassistant.composable

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.HorizontalDivider
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.Button

import androidx.wear.compose.material.ButtonDefaults
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.MaterialTheme
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.FormatTime
import com.gabstra.myworkoutassistant.data.VibrateGentle
import com.gabstra.myworkoutassistant.data.VibrateHard
import com.gabstra.myworkoutassistant.data.VibrateTwice
import com.gabstra.myworkoutassistant.data.VibrateTwiceAndBeep
import com.gabstra.myworkoutassistant.data.WorkoutState
import com.gabstra.myworkoutassistant.presentation.theme.MyColors
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.time.LocalDateTime

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun TimedDurationSetScreen(
    viewModel: AppViewModel,
    modifier: Modifier,
    state: WorkoutState.Set,
    onTimerEnd: () -> Unit,
    onTimerEnabled : () -> Unit,
    onTimerDisabled: () -> Unit,
    extraInfo: (@Composable (WorkoutState.Set) -> Unit)? = null,
    exerciseTitleComposable:  @Composable () -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var timerJob by remember { mutableStateOf<Job?>(null) }

    val set = state.set as TimedDurationSet

    var showStartButton by remember(set) { mutableStateOf(!set.autoStart) }

    var hasBeenStartedOnce by remember { mutableStateOf(false) }

    val previousSet =  state.previousSetData as TimedDurationSetData
    var currentSet by remember(set.id) { mutableStateOf(state.currentSetData as TimedDurationSetData) }

    var isTimerInEditMode by remember { mutableStateOf(false) }

    var lastInteractionTime by remember { mutableLongStateOf(System.currentTimeMillis()) }

    val updateInteractionTime = {
        lastInteractionTime = System.currentTimeMillis()
    }

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

    var currentMillis by remember(set.id) { mutableIntStateOf(currentSet.startTimer) }
    var showStopDialog by remember { mutableStateOf(false) }

    fun onMinusClick(){
        if (currentSet.startTimer > 5000){
            val newTimerValue = currentSet.startTimer - 5000
            currentSet = currentSet.copy(startTimer = newTimerValue)
            currentMillis = newTimerValue
            VibrateGentle(context)
        }
        updateInteractionTime()
    }

    fun onPlusClick(){
        val newTimerValue = currentSet.startTimer + 5000
        currentSet = currentSet.copy(startTimer = newTimerValue)
        currentMillis = newTimerValue
        VibrateGentle(context)
        updateInteractionTime()
    }

    fun startTimerJob() {
        timerJob?.cancel()
        timerJob = scope.launch {
            onTimerEnabled()
            while (currentMillis > 0) {
                delay(1000) // Update every sec.
                currentMillis -= 1000

                currentSet = currentSet.copy(
                    endTimer = currentMillis
                )
            }

            state.currentSetData = currentSet.copy(
                endTimer = 0
            )
            VibrateTwice(context)
            onTimerDisabled()
            onTimerEnd()
        }

        if(!hasBeenStartedOnce){
            hasBeenStartedOnce = true
        }
    }

    LaunchedEffect(set) {
        if (set.autoStart) {
            delay(500)
            VibrateTwice(context)
            startTimerJob()

            if(state.startTime == null){
                state.startTime = LocalDateTime.now()
            }
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

    val textComposable = @Composable {
        val isDifferent = currentSet.startTimer != previousSet.startTimer

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Center
        ) {
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
                                val newTimerValue = previousSet.startTimer
                                currentSet = currentSet.copy(startTimer = newTimerValue)
                                currentMillis = newTimerValue
                                VibrateTwice(context)
                            }
                        }
                    ),
                text = FormatTime(currentMillis / 1000),
                style = MaterialTheme.typography.display2,
                color =  if(isDifferent) MyColors.Orange else Color.Unspecified,
            )
        }
    }

    @Composable
    fun SetScreen(customModifier: Modifier) {
        Column(
            modifier = customModifier,
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(5.dp)
        ) {
            textComposable()
            if (showStartButton) {
                Button(
                    modifier = Modifier.size(35.dp),
                    onClick = {
                        VibrateGentle(context)
                        startTimerJob()

                        if(state.startTime == null){
                            state.startTime = LocalDateTime.now()
                        }

                        showStartButton=false
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

    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
        modifier = modifier
    ) {
        if (isTimerInEditMode) {
            ControlButtonsVertical(
                modifier = Modifier
                    .wrapContentSize()
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
        }
        else
        {
            Column(
                modifier = Modifier.fillMaxSize(),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(5.dp)
            ){
                exerciseTitleComposable()
                Box(
                    modifier = Modifier.weight(1f),
                    contentAlignment = Alignment.Center
                ){
                    Column(
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.spacedBy(5.dp)
                    ) {
                        SetScreen(customModifier = Modifier.weight(1f))
                        if (extraInfo != null) {
                            HorizontalDivider(modifier = Modifier.fillMaxWidth(), thickness = 1.dp)
                            extraInfo(state)
                        }
                    }
                }
            }
        }
    }

    CustomDialogYesOnLongPress(
        show = showStopDialog,
        title = "Stop exercise",
        message = "Do you want to stop this exercise?",
        handleYesClick = {
            VibrateGentle(context)
            state.currentSetData = currentSet.copy(
                endTimer =  currentMillis
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
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {},
        holdTimeInMillis = 1000
    )
}