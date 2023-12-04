package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.DoubleArrow
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInteropFilter
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.ButtonDefaults
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text

import com.gabstra.myhomeworkoutassistant.data.AppViewModel
import com.gabstra.myhomeworkoutassistant.data.WorkoutState
import com.gabstra.myworkoutassistant.composable.BodyWeightSetScreen
import com.gabstra.myworkoutassistant.composable.CustomDialog
import com.gabstra.myworkoutassistant.composable.EnduranceSetScreen
import com.gabstra.myworkoutassistant.composable.ExerciseIndicator
import com.gabstra.myworkoutassistant.composable.HeartRateCircularChart
import com.gabstra.myworkoutassistant.composable.LockScreen
import com.gabstra.myworkoutassistant.composable.TimedDurationSetScreen
import com.gabstra.myworkoutassistant.composable.WeightSetScreen
import com.gabstra.myworkoutassistant.data.MeasureDataViewModel
import com.gabstra.myworkoutassistant.data.VibrateOnce
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch


@OptIn(ExperimentalFoundationApi::class, ExperimentalComposeUiApi::class)
@Composable
fun ExerciseScreen(
    viewModel: AppViewModel,
    hrViewModel: MeasureDataViewModel,
    state: WorkoutState.Set,
    onScreenLocked: () -> Unit,
    onScreenUnlocked: () -> Unit,
) {
    val context = LocalContext.current

    val scope = rememberCoroutineScope()

    var touchJob by remember { mutableStateOf<Job?>(null) }
    var showLockScreen by remember { mutableStateOf(false) }

    fun startTouchTimer() {
        touchJob?.cancel()
        touchJob = scope.launch {
            delay(5000)  // wait for 10 seconds
            showLockScreen=true
            onScreenLocked()
        }
    }

    var showMainButtons by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        delay(10000)
        startTouchTimer() // start the lock timer immediately
    }

    var showConfirmDialog by remember { mutableStateOf(false) }
    var showSkipDialog by remember { mutableStateOf(false) }
    var enableSkipMode by remember { mutableStateOf(false) }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .pointerInteropFilter {
                if (!showLockScreen) {
                    startTouchTimer()
                }

                false
            },
        contentAlignment = Alignment.Center
    ) {
        HeartRateCircularChart(
            modifier = Modifier.fillMaxSize(),
            hrViewModel
        )

        ExerciseIndicator(
            modifier = Modifier.fillMaxSize(),
            viewModel,
            state
        )

        Column(
            verticalArrangement = Arrangement.Top,
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier
                .fillMaxSize()
                .padding(0.dp, 40.dp,0.dp,20.dp)
        ) {
            Column(
                modifier = Modifier.padding(40.dp,0.dp),
                verticalArrangement = Arrangement.Bottom,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                /*
                Row(){
                    Text(
                        text = "Set: $currentSet/${selectedExerciseGroup.sets} ",
                        textAlign= TextAlign.Center,
                        style = MaterialTheme.typography.caption3,
                    )
                    if(selectedExerciseGroup.exercises.count()!=1) {
                        Spacer(modifier = Modifier.width(5.dp))
                        Text(
                            text = "Part: ${selectedExerciseGroup.exercises.indexOf(selectedExercise) + 1}/${selectedExerciseGroup.exercises.count()}",
                            textAlign = TextAlign.Center,
                            style = MaterialTheme.typography.caption3,
                        )
                    }
                }

                Spacer(modifier = Modifier.height(10.dp))

                 */
                Text(
                    modifier = Modifier
                        .basicMarquee(initialDelayMillis = 3000)
                        .combinedClickable(
                            onClick = {},
                            onLongClick = {
                                enableSkipMode = !enableSkipMode
                            }
                        ),
                    text = state.exerciseName,
                    textAlign = TextAlign.Center,
                    style = MaterialTheme.typography.title3,
                )
            }

            when(state.set){
                is WeightSet -> WeightSetScreen(
                    modifier = Modifier.weight(1f),
                    state = state,
                    forceStopEditMode = showLockScreen,
                    isFooterHidden = !showMainButtons,
                    onEditModeChange = { inEditMode ->
                        showMainButtons = !inEditMode
                    }
                )
                is BodyWeightSet -> BodyWeightSetScreen(
                    modifier = Modifier.weight(1f),
                    state = state,
                    forceStopEditMode = showLockScreen,
                    isFooterHidden = !showMainButtons,
                    onEditModeChange = { inEditMode ->
                        showMainButtons = !inEditMode
                    }
                )
                is TimedDurationSet -> TimedDurationSetScreen(
                    modifier = Modifier.weight(1f),
                    state = state,
                    onTimerStart = {
                        showMainButtons = false
                    },
                    onTimerEnd = {
                        if(state.set.autoStop){
                            viewModel.storeExecutedSetHistory(state)
                            viewModel.goToNextState()
                        }else{
                            showMainButtons = true
                        }
                    }
                )
                is EnduranceSet -> EnduranceSetScreen(
                    modifier = Modifier.weight(1f),
                    state = state,
                    onTimerStart = {
                        showMainButtons = false
                    },
                    onTimerEnd = {
                        if(state.set.autoStop){
                            viewModel.storeExecutedSetHistory(state)
                            viewModel.goToNextState()
                        }else{
                            showMainButtons = true
                        }
                    }
                )
            }

            if (showMainButtons) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.End
                ) {
                    if(enableSkipMode){
                        Button(
                            onClick = {
                                VibrateOnce(context)
                                showSkipDialog = true
                            },
                            modifier = Modifier.size(35.dp),
                            colors = ButtonDefaults.buttonColors(backgroundColor = Color.Gray)
                        ) {
                            Icon(imageVector = Icons.Default.DoubleArrow, contentDescription = "skip")
                        }
                    }else{
                        Button(
                            onClick = {
                                VibrateOnce(context)
                                showConfirmDialog=true
                            },
                            modifier = Modifier.size(35.dp),
                            colors = ButtonDefaults.buttonColors(backgroundColor = MaterialTheme.colors.primary)
                        ) {
                            Icon(imageVector = Icons.Default.Check, contentDescription = "Done")
                        }
                    }
                }
            }
        }
    }

    LockScreen(
        show = showLockScreen,
        onUnlock = {
            onScreenUnlocked()
            startTouchTimer()
            showLockScreen = false
        }
    )

    CustomDialog(
        show = showConfirmDialog,
        title = "Complete exercise",
        message = "Do you want to save this data?",
        handleYesClick = {
            VibrateOnce(context)
            viewModel.storeExecutedSetHistory(state)
            viewModel.goToNextState()
            showConfirmDialog=false
        },
        handleNoClick = {
            VibrateOnce(context)
            showConfirmDialog = false
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            showConfirmDialog = false
        }
    )

    CustomDialog(
        show = showSkipDialog,
        title = "Skip exercise",
        message = "Do you want to skip this exercise?",
        handleYesClick = {
            VibrateOnce(context)
            viewModel.storeExecutedSetHistory(state)
            viewModel.goToNextState()
            showSkipDialog = false
        },
        handleNoClick = {
            VibrateOnce(context)
            showSkipDialog = false
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            showSkipDialog = false
        }
    )
}
