package com.gabstra.myworkoutassistant.composable

import android.util.Log
import android.widget.Toast
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
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
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
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import kotlinx.coroutines.delay

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun WeightSetScreen (
    viewModel: AppViewModel,
    modifier: Modifier,
    state: WorkoutState.Set,
    forceStopEditMode: Boolean,
    bottom: @Composable () -> Unit,
    onEditModeEnabled : () -> Unit,
    onEditModeDisabled: () -> Unit
){
    val context = LocalContext.current

    val previousSet = state.previousSetData as WeightSetData
    var currentSet by remember { mutableStateOf(state.currentSetData as WeightSetData) }

    var isRepsInEditMode by remember { mutableStateOf(false) }
    var isWeightInEditMode by remember { mutableStateOf(false) }

    var lastInteractionTime by remember { mutableLongStateOf(System.currentTimeMillis()) }

    val updateInteractionTime = {
        lastInteractionTime = System.currentTimeMillis()
    }

    val currentVolume = (currentSet.actualReps*currentSet.actualWeight).toInt()
    val previousVolume = (previousSet.actualReps*previousSet.actualWeight).toInt()

    val isInEditMode = isRepsInEditMode || isWeightInEditMode

    LaunchedEffect(currentSet) {
        state.currentSetData = currentSet
    }

    LaunchedEffect(isInEditMode) {
        if (isInEditMode) {
            onEditModeEnabled()
            while (isInEditMode) {
                if (System.currentTimeMillis() - lastInteractionTime > 5000) {
                    isRepsInEditMode = false
                    isWeightInEditMode = false
                }
                delay(1000) // Check every second
            }
        } else {
            onEditModeDisabled()
        }
    }

    LaunchedEffect(forceStopEditMode) {
        if(forceStopEditMode){
            isRepsInEditMode = false
            isWeightInEditMode = false
        }
    }


    fun onMinusClick(){
        updateInteractionTime()
        if (isRepsInEditMode && (currentSet.actualReps > 1)){
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
        updateInteractionTime()
        if (isRepsInEditMode){
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
                            updateInteractionTime()
                            isWeightInEditMode = false
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
                            updateInteractionTime()
                            isRepsInEditMode = false
                        }
                        VibrateOnce(context)
                    },
                    onDoubleClick = {
                        if (isWeightInEditMode) {
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
                    Column(modifier = Modifier.padding(0.dp,0.dp,30.dp,0.dp)) {
                        if (isRepsInEditMode) repsRow()
                        if (isWeightInEditMode) weightRow()
                    }
                }
            )

        }else{
            Row(
                modifier = Modifier.fillMaxWidth().padding(0.dp, 0.dp, 30.dp, 2.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.End
            ) {
                TrendIcon(currentVolume, previousVolume)
                Column(Modifier.width(95.dp)){
                    repsRow()
                    Spacer(modifier = Modifier.height(5.dp))
                    weightRow()
                }
            }
            
            Box(contentAlignment = Alignment.BottomCenter) {
                bottom()
            }
        }
    }
}