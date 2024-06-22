package com.gabstra.myworkoutassistant.composable

import android.util.Log
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Stop
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.ButtonDefaults
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.AppViewModel

import com.gabstra.myworkoutassistant.data.FormatTime
import com.gabstra.myworkoutassistant.data.VibrateOnce
import com.gabstra.myworkoutassistant.data.VibrateShortImpulse
import com.gabstra.myworkoutassistant.data.VibrateTwice
import com.gabstra.myworkoutassistant.data.WorkoutState
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun EnduranceSetScreen (viewModel: AppViewModel, modifier: Modifier, state: WorkoutState.Set, onTimerEnd: () -> Unit, bottom: @Composable () -> Unit, onTimerEnabled : () -> Unit, onTimerDisabled: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var timerJob by remember { mutableStateOf<Job?>(null) }

    val set = state.set as EnduranceSet

    var showStartButton by remember(set) { mutableStateOf(!set.autoStart) }

    val previousSet = state.previousSetData as EnduranceSetData
    var currentSet by remember(state.set.id) { mutableStateOf(state.currentSetData as EnduranceSetData) }

    var isTimerInEditMode by remember { mutableStateOf(false) }

    val stopScrolling = isTimerInEditMode || timerJob?.isActive == true

    LaunchedEffect(currentSet) {
        viewModel.updateCurrentSetData(currentSet)
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

    var showBottom by remember { mutableStateOf(false) }

    fun onMinusClick(){
        if (currentSet.startTimer > 5000){
            currentSet = currentSet.copy(startTimer = currentSet.startTimer - 5000)
            VibrateOnce(context)
        }
    }

    fun onPlusClick(){
        currentSet = currentSet.copy(startTimer = currentSet.startTimer + 5000)
        VibrateOnce(context)
    }

    var textComposable = @Composable {
        Text(
            modifier = Modifier.combinedClickable(
                onClick = {
                },
                onLongClick = {
                    if (showStartButton) {
                        isTimerInEditMode = !isTimerInEditMode
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
            text = FormatTime((if(isTimerInEditMode) currentSet.startTimer else currentMillis) / 1000),
            style = if(isTimerInEditMode)  MaterialTheme.typography.display2 else MaterialTheme.typography.display1,
        )
    }

    fun startTimerJob() {
        timerJob?.cancel()
        timerJob = scope.launch {
            while (currentMillis < set.timeInMillis) {
                delay(1000) // Update every sec.
                currentMillis += 1000

                currentSet = currentSet.copy(
                    endTimer = currentMillis
                )

                if (currentMillis >= (currentSet.startTimer-3000))
                    VibrateOnce(context);
            }

            currentSet = currentSet.copy(
                endTimer = currentSet.startTimer
            )
            viewModel.updateCurrentSetData(currentSet)
            VibrateShortImpulse(context);
            onTimerEnd()

            if(!set.autoStop){
                showBottom = true
            }
        }
    }

    LaunchedEffect(set) {
        if (set.autoStart) {
            delay(500)
            startTimerJob()
        }
    }

    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        modifier = modifier
    ) {
        if (isTimerInEditMode) {
            ControlButtonsVertical(
                modifier = Modifier.fillMaxSize(),
                onMinusTap = { onMinusClick() },
                onMinusLongPress = { onMinusClick() },
                onPlusTap = { onPlusClick() },
                onPlusLongPress = { onPlusClick() },
                content = {
                    Column(modifier = Modifier.padding(0.dp,5.dp,0.dp,5.dp)) {
                        textComposable()
                    }
                }
            )
        }else{
            Column(modifier = Modifier.padding(vertical= 15.dp), verticalArrangement = Arrangement.Top) {
                textComposable()
            }
            Box(contentAlignment = Alignment.BottomCenter) {
                if (showStartButton) {
                    Button(
                        onClick = {
                            VibrateOnce(context)
                            startTimerJob()
                            showStartButton=false
                        },
                        modifier = Modifier.size(35.dp),
                        colors = ButtonDefaults.buttonColors(backgroundColor = MaterialTheme.colors.primary)
                    ) {
                        Icon(imageVector = Icons.Default.PlayArrow, contentDescription = "Start")
                    }
                }

                if (timerJob?.isActive == true) {
                    Button(
                        onClick = {
                            VibrateOnce(context)
                            timerJob?.cancel()
                            showStopDialog = true
                        },
                        modifier = Modifier.size(35.dp),
                        colors = ButtonDefaults.buttonColors(backgroundColor = MaterialTheme.colors.error)
                    ) {
                        Icon(imageVector = Icons.Default.Stop, contentDescription = "Stop")
                    }
                } else if(showBottom){
                    bottom()
                }
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
            viewModel.updateCurrentSetData(currentSet)
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