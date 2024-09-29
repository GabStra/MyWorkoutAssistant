package com.gabstra.myworkoutassistant.composable

import android.util.Log
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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
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
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.ButtonDefaults
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.AppViewModel

import com.gabstra.myworkoutassistant.data.FormatTime
import com.gabstra.myworkoutassistant.data.PlayBeep
import com.gabstra.myworkoutassistant.data.PlayNBeeps
import com.gabstra.myworkoutassistant.data.VibrateAndBeep
import com.gabstra.myworkoutassistant.data.VibrateOnce
import com.gabstra.myworkoutassistant.data.VibrateShortImpulse
import com.gabstra.myworkoutassistant.data.VibrateShortImpulseAndBeep
import com.gabstra.myworkoutassistant.data.VibrateTwice
import com.gabstra.myworkoutassistant.data.VibrateTwiceAndBeep
import com.gabstra.myworkoutassistant.data.WorkoutState
import com.gabstra.myworkoutassistant.presentation.theme.MyColors
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun EnduranceSetScreen (
    viewModel: AppViewModel,
    modifier: Modifier,
    state: WorkoutState.Set,
    onTimerEnd: () -> Unit,
    onTimerEnabled : () -> Unit,
    onTimerDisabled: () -> Unit,
    extraInfo: (@Composable (WorkoutState.Set) -> Unit)? = null
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var timerJob by remember { mutableStateOf<Job?>(null) }

    var hasBeenStartedOnce by remember { mutableStateOf(false) }

    var isOverLimit by remember { mutableStateOf(false) }

    val set = state.set as EnduranceSet

    var showStartButton by remember(set) { mutableStateOf(!set.autoStart) }

    val previousSet = state.previousSetData as EnduranceSetData
    var currentSet by remember(state.set.id) { mutableStateOf(state.currentSetData as EnduranceSetData) }

    var isTimerInEditMode by remember { mutableStateOf(false) }

    val stopScrolling = isTimerInEditMode || timerJob?.isActive == true

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

    LaunchedEffect(stopScrolling) {
        if (stopScrolling) {
            onTimerEnabled()
        } else {
            onTimerDisabled()
        }
    }

    var currentMillis by remember(state.set.id) { mutableIntStateOf(0) }
    var showStopDialog by remember { mutableStateOf(false) }

    fun onMinusClick(){
        if (currentSet.startTimer > 5000){
            currentSet = currentSet.copy(startTimer = currentSet.startTimer - 5000)
            VibrateOnce(context)
        }
        updateInteractionTime()
    }

    fun onPlusClick(){
        currentSet = currentSet.copy(startTimer = currentSet.startTimer + 5000)
        VibrateOnce(context)
        updateInteractionTime()
    }

    val textComposable = @Composable {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp),
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
                            VibrateOnce(context)
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
                color = if(isOverLimit) MyColors.Green else Color.Unspecified,
                text = FormatTime((if(isTimerInEditMode) currentSet.startTimer else currentMillis) / 1000),
                style = MaterialTheme.typography.display2,
            )
        }
    }

    fun startTimerJob() {
        timerJob?.cancel()
        timerJob = scope.launch {
            while (true) {
                delay(1000) // Update every sec.
                currentMillis += 1000

                currentSet = currentSet.copy(
                    endTimer = currentMillis
                )

                if(isOverLimit) continue

                if (currentMillis >= (currentSet.startTimer-3000) && currentMillis < currentSet.startTimer) {
                    VibrateAndBeep(context)
                }

                if(currentMillis >= currentSet.startTimer){
                    VibrateTwiceAndBeep(context)
                    if(set.autoStop) break
                    else isOverLimit = true
                }
            }

            state.currentSetData = currentSet
            onTimerEnd()
        }

        if(!hasBeenStartedOnce){
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
        if (set.autoStart) {
            delay(500)
            VibrateAndBeep(context)
            delay(1000)
            VibrateAndBeep(context)
            delay(1000)
            VibrateAndBeep(context)
            delay(1000)
            VibrateTwiceAndBeep(context)
            delay(500)
            startTimerJob()
        }
    }

    @Composable
    fun SetScreen(customModifier: Modifier) {
        Column(
            modifier = customModifier,
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center
        ) {
            textComposable()
            if (showStartButton) {
                EnhancedButton(
                    boxModifier = Modifier.weight(1f),
                    onClick = {
                        VibrateOnce(context)
                        startTimerJob()
                        showStartButton = false
                    },
                    buttonSize = 35.dp,
                    colors = ButtonDefaults.buttonColors(backgroundColor = MyColors.Green)
                ) {
                    Icon(imageVector = Icons.Default.PlayArrow, contentDescription = "Start")
                }
            }else{
                EnhancedButton(
                    boxModifier = Modifier.weight(1f).alpha(if(timerJob?.isActive == true) 1f else 0f),
                    onClick = {
                        VibrateOnce(context)
                        timerJob?.cancel()
                        showStopDialog = true
                    },
                    buttonSize = 35.dp,
                    colors = ButtonDefaults.buttonColors(backgroundColor = MaterialTheme.colors.error)
                ) {
                    Icon(imageVector = Icons.Default.Stop, contentDescription = "Stop",tint = Color.Black)
                }
            }
        }
    }

    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
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
            if(extraInfo != null){
                Column(
                    modifier = Modifier.fillMaxSize(),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(5.dp)
                ){
                    SetScreen(customModifier = Modifier.weight(1f))
                    HorizontalDivider(modifier = Modifier.fillMaxWidth(), thickness = 1.dp)
                    extraInfo(state)
                }
            }else{
                SetScreen(customModifier = Modifier.fillMaxSize())
            }
        }
    }

    CustomDialogYesOnLongPress(
        show = showStopDialog,
        title = "Stop exercise",
        message = "Do you want to stop this exercise?",
        handleYesClick = {
            VibrateOnce(context)
            currentSet = currentSet.copy(
                endTimer = currentMillis
            )

            onTimerEnd()
            showStopDialog = false
        },
        handleNoClick = {
            VibrateOnce(context)
            showStopDialog = false
            startTimerJob()
        },
        handleOnAutomaticClose = {},
        holdTimeInMillis = 1000
    )
}