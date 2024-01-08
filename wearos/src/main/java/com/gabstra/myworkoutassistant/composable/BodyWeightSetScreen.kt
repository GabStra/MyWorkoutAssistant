package com.gabstra.myworkoutassistant.composable

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowRight
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
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myhomeworkoutassistant.data.WorkoutState
import com.gabstra.myworkoutassistant.data.VibrateOnce
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun BodyWeightSetScreen(modifier: Modifier, state: WorkoutState.Set, forceStopEditMode: Boolean, isFooterHidden:Boolean, onEditModeChange: (Boolean) -> Unit) {
    val context = LocalContext.current

    val previousSet = state.previousSetData as BodyWeightSetData
    var currentSet by remember { mutableStateOf(state.currentSetData as BodyWeightSetData) }

    var isRepsPickerVisible by remember { mutableStateOf(false) }

    LaunchedEffect(forceStopEditMode) {
        if(forceStopEditMode) isRepsPickerVisible = false
    }

    LaunchedEffect(isRepsPickerVisible) {
        onEditModeChange(isRepsPickerVisible)
    }

    LaunchedEffect(currentSet) {
        // Update the WorkoutState.Set whenever currentSet changes
        state.currentSetData = currentSet
    }

    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        modifier = modifier
    ){
        Column(modifier = Modifier.weight(1f).padding(40.dp,20.dp,40.dp,0.dp), verticalArrangement = Arrangement.Top, horizontalAlignment = Alignment.End) {
            Row(
                modifier = Modifier.combinedClickable(
                    onClick = {
                        if(!forceStopEditMode) isRepsPickerVisible = !isRepsPickerVisible
                    },
                    onLongClick = {
                        if (isRepsPickerVisible) {
                            currentSet= previousSet.copy()
                            VibrateOnce(context)
                        }
                    }
                ),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.End
            ) {
                if (isRepsPickerVisible) {
                    Icon(
                        imageVector = Icons.AutoMirrored.Filled.ArrowRight,
                        contentDescription = "Same",
                        modifier = Modifier.size(35.dp)
                    )
                }else{
                    if(currentSet.actualReps != 0 && !isRepsPickerVisible) TrendIcon(currentSet.actualReps, previousSet.actualReps)
                    Spacer(modifier = Modifier.width(5.dp))
                }
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
                        modifier = Modifier.width(35.dp).padding(0.dp,0.dp,0.dp,4.dp)
                    )
                }
            }
        }
        Box(contentAlignment = Alignment.BottomCenter) {
            if (isFooterHidden && isRepsPickerVisible) {
                ControlButtons(
                    onMinusClick = {
                        if (currentSet.actualReps > 1) currentSet = currentSet.copy(actualReps = currentSet.actualReps - 1)
                    },
                    onPlusClick = {
                        currentSet = currentSet.copy(actualReps = currentSet.actualReps + 1)
                    }
                )
            }
        }
    }
}