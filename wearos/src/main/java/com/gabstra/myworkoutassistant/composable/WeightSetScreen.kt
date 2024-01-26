package com.gabstra.myworkoutassistant.composable

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.interaction.collectIsDraggedAsState
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
import androidx.compose.foundation.pager.PagerState
import androidx.compose.foundation.pager.rememberPagerState
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
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.util.lerp
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.VibrateOnce
import com.gabstra.myworkoutassistant.data.WorkoutState
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.google.android.horologist.compose.pager.PagerScreen
import kotlin.math.absoluteValue

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun WeightSetScreen (modifier: Modifier, state: WorkoutState.Set, forceStopEditMode: Boolean, bottom: @Composable () -> Unit) {
    val context = LocalContext.current

    val previousSet = state.previousSetData as WeightSetData
    var currentSet by remember { mutableStateOf(state.currentSetData as WeightSetData) }

    var isRepsPickerVisible by remember { mutableStateOf(false) }
    var isWeightPickerVisible by remember { mutableStateOf(false) }


    LaunchedEffect(forceStopEditMode) {
        if(forceStopEditMode){
            isRepsPickerVisible = false
            isWeightPickerVisible = false
        }
    }

    LaunchedEffect(currentSet) {
        // Update the WorkoutState.Set whenever currentSet changes
        state.currentSetData = currentSet
    }

    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        modifier = Modifier
            .fillMaxSize()
    ){
        Column(modifier = Modifier.padding(25.dp,2.dp,30.dp,2.dp), verticalArrangement = Arrangement.Top, horizontalAlignment = Alignment.End) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .combinedClickable(
                        onClick = {
                            if (!forceStopEditMode) {
                                isRepsPickerVisible = !isRepsPickerVisible
                                isWeightPickerVisible = false
                            }
                        },
                        onLongClick = {
                            if (isRepsPickerVisible) {
                                currentSet = currentSet.copy(
                                    actualReps = previousSet.actualReps
                                )
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
                        modifier = Modifier
                            .width(35.dp)
                            .padding(0.dp, 0.dp, 0.dp, 4.dp)
                    )
                }
            }
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .combinedClickable(
                        onClick = {
                            if (!forceStopEditMode) {
                                isWeightPickerVisible = !isWeightPickerVisible
                                isRepsPickerVisible = false
                            }
                        },
                        onLongClick = {
                            if (isWeightPickerVisible) {
                                currentSet = currentSet.copy(
                                    actualWeight = previousSet.actualWeight
                                )
                                VibrateOnce(context)
                            }
                        }
                    ),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.End
            ) {
                if (isWeightPickerVisible) {
                    Icon(
                        imageVector = Icons.AutoMirrored.Filled.ArrowRight,
                        contentDescription = "Same",
                        modifier = Modifier.size(35.dp)
                    )
                }else{
                    if(!isWeightPickerVisible) TrendIcon(currentSet.actualWeight, previousSet.actualWeight)
                    Spacer(modifier = Modifier.width(5.dp))
                }

                Row(
                    verticalAlignment = Alignment.Bottom,
                    horizontalArrangement = Arrangement.End
                ) {
                    Text(
                        text = "${currentSet.actualWeight}",
                        style = MaterialTheme.typography.display3
                    )
                    Spacer(modifier = Modifier.width(5.dp))
                    Text(
                        text = "kg",
                        style = MaterialTheme.typography.body1,
                        modifier = Modifier
                            .width(35.dp)
                            .padding(0.dp, 0.dp, 0.dp, 4.dp)
                    )
                }
            }
        }

        Box(contentAlignment = Alignment.BottomCenter) {
            if (isRepsPickerVisible || isWeightPickerVisible) {
                Spacer(modifier = Modifier.height(10.dp))
                ControlButtons(
                    onMinusClick = {
                        if (isRepsPickerVisible && currentSet.actualReps>1){
                            currentSet = currentSet.copy(
                                actualReps = currentSet.actualReps-1
                            )
                        }
                        if (isWeightPickerVisible && (currentSet.actualWeight > 0.5)){
                            currentSet = currentSet.copy(
                                actualWeight = currentSet.actualWeight.minus(0.5F)
                            )
                        }
                    },
                    onPlusClick = {
                        if (isRepsPickerVisible && currentSet.actualReps>1){
                            currentSet = currentSet.copy(
                                actualReps = currentSet.actualReps+1
                            )
                        }
                        if (isWeightPickerVisible){
                            currentSet = currentSet.copy(
                                actualWeight = currentSet.actualWeight.plus(0.5F)
                            )
                        }
                    }
                )
            }else{
                bottom()
            }
        }
    }
}