package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowRight
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.DoubleArrow
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
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
import com.gabstra.myworkoutassistant.composable.ControlButtons
import com.gabstra.myworkoutassistant.composable.CustomDialog
import com.gabstra.myworkoutassistant.composable.HeartRateCircularChart
import com.gabstra.myworkoutassistant.composable.LockScreen
import com.gabstra.myworkoutassistant.composable.TrendIcon
import com.gabstra.myworkoutassistant.data.MeasureDataViewModel
import com.gabstra.myworkoutassistant.data.VibrateOnce
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch


@OptIn(ExperimentalFoundationApi::class, ExperimentalComposeUiApi::class)
@Composable
fun ExerciseScreen(
    viewModel: AppViewModel,
    hrViewModel: MeasureDataViewModel,
    state: WorkoutState.Exercise,
    onScreenLocked: () -> Unit,
    onScreenUnlocked: () -> Unit,
) {
    val context = LocalContext.current

    val scope = rememberCoroutineScope()
    var showLockScreen by remember { mutableStateOf(false) }
    var touchJob by remember { mutableStateOf<Job?>(null) }

    fun resetTouchTimer() {
        touchJob?.cancel()
        touchJob = scope.launch {
            delay(5000)  // wait for 10 seconds
            showLockScreen=true
            onScreenLocked()
        }
    }


    LaunchedEffect(Unit) {
        resetTouchTimer() // start the lock timer immediately

        /*
        delay(500)
        showLockScreen=true // Start the lock immediately
        onScreenLocked()
        */
    }

    var showConfirmDialog by remember { mutableStateOf(false) }
    var enableSkipMode by remember { mutableStateOf(false) }


    val bodyWeight = remember { state.weight == null || state.weight == 0.0F }

    var isRepsPickerVisible by remember { mutableStateOf(false) }
    var isWeightPickerVisible by remember { mutableStateOf(false) }

    val latestReps = state.reps
    val latestWeights = state.weight

    var executedReps by remember(latestReps) { mutableIntStateOf(latestReps) }
    var usedWeightsInKGs by remember(latestWeights) { mutableStateOf(latestWeights) }

    val currentSet = state.currentSet
    val selectedExerciseGroup = state.exerciseGroup
    val selectedExercise = state.exercise

    CustomDialog(
        show = showConfirmDialog,
        title = "Complete exercise",
        message = "Do you want to save this data?",
        handleYesClick = {
            VibrateOnce(context)
            viewModel.storeExecutedExerciseHistory(executedReps,usedWeightsInKGs)
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

    Box(
        modifier = Modifier
            .fillMaxSize()
            .pointerInteropFilter { event ->
                if(!showLockScreen){
                    resetTouchTimer()
                }

                false
            },
        contentAlignment = Alignment.Center
    ) {
        HeartRateCircularChart(
            modifier = Modifier.fillMaxSize(),
            hrViewModel
        )

        Column(
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier
                .fillMaxSize()
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically
            ){

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

            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 40.dp)
                    .combinedClickable(
                        onClick = {},
                        onLongClick = {
                            enableSkipMode=!enableSkipMode
                        }
                    ),
                contentAlignment = Alignment.BottomCenter
            ) {
                Text(
                    modifier = Modifier.basicMarquee(),
                    text = selectedExercise.name,
                    textAlign = TextAlign.Center,
                    style = MaterialTheme.typography.title3,
                )
            }

            Spacer(modifier = Modifier.height(10.dp))

            Row(
                modifier = Modifier.combinedClickable(
                    onClick = {
                        if (!isWeightPickerVisible) isRepsPickerVisible = !isRepsPickerVisible
                    },
                    onLongClick = {
                        if (isRepsPickerVisible) {
                            executedReps = latestReps
                            VibrateOnce(context)
                        }
                    }
                ),
                verticalAlignment = Alignment.CenterVertically

            ) {
                if(!isWeightPickerVisible){
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.Start
                    ) {
                        if (isRepsPickerVisible) {
                            Icon(
                                imageVector = Icons.AutoMirrored.Filled.ArrowRight,
                                contentDescription = "Same",
                                modifier = Modifier.size(24.dp)
                            )
                            Spacer(modifier = Modifier.width(5.dp))
                        }
                        Text(
                            text = if(executedReps == 0) "Skipped" else "$executedReps reps",
                            style = MaterialTheme.typography.body2
                        )
                        Spacer(modifier = Modifier.width(5.dp))
                        if(executedReps != 0) TrendIcon(executedReps, latestReps)
                    }
                }
            }

            if (!bodyWeight && !isRepsPickerVisible) {
                Spacer(modifier = Modifier.height(4.dp))

                Row(
                    modifier = Modifier.combinedClickable(
                        onClick = {
                            if (!isRepsPickerVisible) isWeightPickerVisible = !isWeightPickerVisible
                        },
                        onLongClick = {
                            if (isWeightPickerVisible) {
                                usedWeightsInKGs = latestWeights
                                VibrateOnce(context)
                            }

                        }
                    ),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.End
                    ) {
                        if (isWeightPickerVisible) {
                            Icon(
                                imageVector = Icons.AutoMirrored.Filled.ArrowRight,
                                contentDescription = "Pick",
                                modifier = Modifier.size(24.dp)
                            )
                            Spacer(modifier = Modifier.width(5.dp))
                        }
                        Text(
                            text = "$usedWeightsInKGs kg",
                            style = MaterialTheme.typography.body2
                        )
                        Spacer(modifier = Modifier.width(5.dp))
                        TrendIcon(usedWeightsInKGs!!, latestWeights!!)
                    }
                }
            }
            Spacer(modifier = Modifier.height(20.dp))

            if (isRepsPickerVisible || isWeightPickerVisible) {
                ControlButtons(
                    onMinusClick = {
                        if (isRepsPickerVisible && executedReps>1) executedReps--
                        if (isWeightPickerVisible && (usedWeightsInKGs!! > 0.5)) usedWeightsInKGs = usedWeightsInKGs?.minus(
                            0.5F
                        )
                    },
                    onPlusClick = {
                        if (isRepsPickerVisible) executedReps++
                        if (isWeightPickerVisible) usedWeightsInKGs = usedWeightsInKGs?.plus(0.5F)
                    }
                )
            } else {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.End
                ) {
                    if(enableSkipMode){
                        Button(
                            onClick = {
                                VibrateOnce(context)
                                executedReps=0
                                enableSkipMode=false
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
            resetTouchTimer()
            showLockScreen = false
        }
    )
}
