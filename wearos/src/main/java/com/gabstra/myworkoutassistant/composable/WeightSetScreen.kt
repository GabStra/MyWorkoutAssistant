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
import androidx.compose.foundation.layout.height
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
import com.gabstra.myworkoutassistant.data.VibrateOnce
import com.gabstra.myworkoutassistant.data.VibrateTwice
import com.gabstra.myworkoutassistant.data.WorkoutState
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun WeightSetScreen (modifier: Modifier, state: WorkoutState.Set, forceStopEditMode: Boolean, bottom: @Composable () -> Unit) {
    val context = LocalContext.current

    val previousSet = state.previousSetData as WeightSetData
    var currentSet by remember { mutableStateOf(state.currentSetData as WeightSetData) }

    var isRepsInEditMode by remember { mutableStateOf(false) }
    var isWeightInEditMode by remember { mutableStateOf(false) }


    LaunchedEffect(forceStopEditMode) {
        if(forceStopEditMode){
            isRepsInEditMode = false
            isWeightInEditMode = false
        }
    }

    LaunchedEffect(currentSet) {
        // Update the WorkoutState.Set whenever currentSet changes
        state.currentSetData = currentSet
    }

    fun onMinusClick(){
        if (isRepsInEditMode && currentSet.actualReps>1){
            currentSet = currentSet.copy(
                actualReps = currentSet.actualReps-1
            )
            VibrateOnce(context)
        }
        if (isWeightInEditMode && (currentSet.actualWeight > 0.5)){
            currentSet = currentSet.copy(
                actualWeight = currentSet.actualWeight.minus(0.5F)
            )
            VibrateOnce(context)
        }

    }

    fun onPlusClick(){
        if (isRepsInEditMode && currentSet.actualReps>1){
            currentSet = currentSet.copy(
                actualReps = currentSet.actualReps+1
            )
            VibrateOnce(context)
        }
        if (isWeightInEditMode){
            currentSet = currentSet.copy(
                actualWeight = currentSet.actualWeight.plus(0.5F)
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
                            isWeightInEditMode = false
                        }

                        VibrateOnce(context)
                    },
                    onDoubleClick = {
                        if (!isRepsInEditMode) {
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
                    style = MaterialTheme.typography.title1
                )
                Spacer(modifier = Modifier.width(5.dp))
                Text(
                    text = "reps",
                    style = MaterialTheme.typography.body1,
                    modifier = Modifier
                        .width(35.dp)
                        .padding(0.dp, 0.dp, 0.dp, 1.dp)
                )
            }
        }
    }

    val weightRow = @Composable {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .combinedClickable(
                    onClick = {
                    },
                    onLongClick = {
                        if (!forceStopEditMode) {
                            isWeightInEditMode = !isWeightInEditMode
                            isRepsInEditMode = false
                        }
                        VibrateOnce(context)
                    },
                    onDoubleClick = {
                        if (!isWeightInEditMode) {
                            currentSet = currentSet.copy(
                                actualWeight = previousSet.actualWeight
                            )
                            VibrateTwice(context)
                        }
                    }
                ),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.End
        ) {
            TrendIcon(currentSet.actualWeight, previousSet.actualWeight)
            Spacer(modifier = Modifier.width(5.dp))

            Row(
                verticalAlignment = Alignment.Bottom,
                horizontalArrangement = Arrangement.End
            ) {
                Text(
                    text = "${currentSet.actualWeight}",
                    style = MaterialTheme.typography.title1
                )
                Spacer(modifier = Modifier.width(5.dp))
                Text(
                    text = "kg",
                    style = MaterialTheme.typography.body1,
                    modifier = Modifier
                        .width(35.dp)
                        .padding(0.dp, 0.dp, 0.dp, 1.dp)
                )
            }
        }
    }

    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
        modifier = Modifier
            .fillMaxSize()
    ){
        if (isRepsInEditMode || isWeightInEditMode) {
            ControlButtonsVertical(
                modifier = Modifier.fillMaxSize(),
                onMinusClick = { onMinusClick() },
                onMinusLongPress = { onMinusClick() },
                onPlusClick = { onPlusClick() },
                onPlusLongPress = { onPlusClick() },
                content = {
                    Column(modifier = Modifier.padding(0.dp,0.dp,30.dp,0.dp)) {
                        if (isRepsInEditMode) repsRow()
                        if (isWeightInEditMode) weightRow()
                    }
                }
            )

        }else{
            Column(modifier = Modifier.padding(0.dp,0.dp,30.dp,2.dp).weight(1f), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.End) {
                repsRow()
                Spacer(modifier = Modifier.height(5.dp))
                weightRow()
            }

            Box(contentAlignment = Alignment.BottomCenter) {
                bottom()
            }
        }
    }
}