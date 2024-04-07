package com.gabstra.myworkoutassistant.composable

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.VibrateOnce
import com.gabstra.myworkoutassistant.data.VibrateTwice
import com.gabstra.myworkoutassistant.data.WorkoutState
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun BodyWeightSetScreen(viewModel: AppViewModel, modifier: Modifier, state: WorkoutState.Set, forceStopEditMode: Boolean, bottom: @Composable () -> Unit, onEditModeEnabled : () -> Unit, onEditModeDisabled: () -> Unit) {
    val context = LocalContext.current

    val previousSet = state.previousSetData as BodyWeightSetData
    var currentSet by remember { mutableStateOf(state.currentSetData as BodyWeightSetData) }

    var isRepsInEditMode by remember { mutableStateOf(false) }

    LaunchedEffect(forceStopEditMode) {
        if(forceStopEditMode) isRepsInEditMode = false
    }

    LaunchedEffect(isRepsInEditMode) {
        if (isRepsInEditMode) {
            onEditModeEnabled()
        } else {
            onEditModeDisabled()
        }
    }

    fun onMinusClick(){
        if (isRepsInEditMode && currentSet.actualReps>1){
            currentSet = currentSet.copy(
                actualReps = currentSet.actualReps-1
            )
            VibrateOnce(context)
        }
    }

    fun onPlusClick(){
        if (isRepsInEditMode){
            currentSet = currentSet.copy(
                actualReps = currentSet.actualReps+1
            )
            VibrateOnce(context)
        }
    }

    val repsRow = @Composable {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .combinedClickable(
                    onClick = {
                    },
                    onLongClick = {
                        if (!forceStopEditMode) {
                            isRepsInEditMode = !isRepsInEditMode
                        }

                        VibrateOnce(context)
                    },
                    onDoubleClick = {
                        if (isRepsInEditMode) {
                            currentSet = currentSet.copy(
                                actualReps = previousSet.actualReps
                            )

                            VibrateTwice(context)
                        }
                    }
                ),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.End
        ) {
            TrendIcon(currentSet.actualReps, previousSet.actualReps)
            Spacer(modifier = Modifier.width(5.dp))

            Row(
                verticalAlignment = Alignment.Bottom,
                horizontalArrangement = Arrangement.End
            ) {

                Text(
                    text = "${currentSet.actualReps}",
                    style = MaterialTheme.typography.display3
                )
                Spacer(modifier = Modifier.width(5.dp))
                Text(
                    text = "reps",
                    style = MaterialTheme.typography.body1,
                    modifier = Modifier
                        .width(35.dp)
                        .padding(0.dp, 0.dp, 0.dp, 3.dp)
                )
            }
        }
    }

    LaunchedEffect(currentSet) {
        // Update the WorkoutState.Set whenever currentSet changes
        state.currentSetData = currentSet
    }

    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
        modifier = modifier
    ){
        if (isRepsInEditMode) {
            ControlButtonsVertical(
                modifier = Modifier.fillMaxSize(),
                onMinusTap = { onMinusClick() },
                onMinusLongPress = { onMinusClick() },
                onPlusTap = { onPlusClick() },
                onPlusLongPress = { onPlusClick() },
                content = {
                    Column(modifier = Modifier.padding(0.dp,0.dp,30.dp,0.dp)) {
                        repsRow()
                    }
                }
            )

        }else{
            Column(modifier = Modifier.padding(0.dp,0.dp,30.dp,2.dp).weight(1f), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.End) {
                repsRow()
            }

            Box(contentAlignment = Alignment.BottomCenter) {
                bottom()
            }
        }
    }
}