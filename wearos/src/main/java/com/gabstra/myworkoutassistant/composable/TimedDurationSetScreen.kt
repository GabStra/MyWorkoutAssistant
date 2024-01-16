package com.gabstra.myworkoutassistant.composable

import androidx.compose.foundation.ExperimentalFoundationApi
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.ButtonDefaults
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.FormatTime
import com.gabstra.myworkoutassistant.data.VibrateOnce
import com.gabstra.myworkoutassistant.data.VibrateShortImpulse
import com.gabstra.myworkoutassistant.data.WorkoutState
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun TimedDurationSetScreen(modifier: Modifier, state: WorkoutState.Set, onTimerStart: () -> Unit, onTimerEnd: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var timerJob by remember { mutableStateOf<Job?>(null) }

    val set = state.set as TimedDurationSet

    var showStartButton by remember(state) { mutableStateOf(!state.set.autoStart) }

    val previousSet = state.previousSetData as TimedDurationSetData
    val currentSet = state.currentSetData as TimedDurationSetData

    var currentMillis by remember(state) { mutableIntStateOf(state.set.timeInMillis) }
    var showStopDialog by remember { mutableStateOf(false) }

    fun startTimerJob() {
        timerJob?.cancel()
        timerJob = scope.launch {
            onTimerStart()
            while (currentMillis > 0) {
                delay(1000) // Update every sec.
                currentMillis -= 1000

                state.currentSetData = currentSet.copy(
                    actualTimeInMillis = currentMillis
                )

                if (currentMillis <= 3000)
                    VibrateOnce(context);
            }

            state.currentSetData = currentSet.copy(
                actualTimeInMillis = 0
            )

            VibrateShortImpulse(context);
            onTimerEnd()
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
        Column(modifier = Modifier.padding(0.dp,5.dp,0.dp,5.dp), verticalArrangement = Arrangement.Top) {
            Text(
                text = FormatTime(currentMillis / 1000),
                style = MaterialTheme.typography.display1,
            )
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
            }
        }
    }

    CustomDialog(
        show = showStopDialog,
        title = "Stop exercise",
        message = "Do you want to stop this exercise?",
        handleYesClick = {
            VibrateOnce(context)
            state.currentSetData = currentSet.copy(
                actualTimeInMillis = currentMillis
            )
            onTimerEnd()
            showStopDialog = false
        },
        handleNoClick = {
            VibrateOnce(context)
            showStopDialog = false
            startTimerJob()
        },
        handleOnAutomaticClose = {
            showStopDialog = false
            startTimerJob()
        }
    )
}