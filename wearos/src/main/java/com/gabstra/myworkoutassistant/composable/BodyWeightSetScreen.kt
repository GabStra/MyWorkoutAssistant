package com.gabstra.myworkoutassistant.composable

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.material3.HorizontalDivider
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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.VibrateOnce
import com.gabstra.myworkoutassistant.data.VibrateTwice
import com.gabstra.myworkoutassistant.data.WorkoutState
import com.gabstra.myworkoutassistant.data.calculateVolume
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import kotlinx.coroutines.delay

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun BodyWeightSetScreen(
    viewModel: AppViewModel,
    modifier: Modifier,
    state: WorkoutState.Set,
    forceStopEditMode: Boolean,
    onEditModeEnabled : () -> Unit,
    onEditModeDisabled: () -> Unit,
    extraInfo: (@Composable (WorkoutState.Set) -> Unit)? = null
) {
    val context = LocalContext.current

    val exercise = viewModel.exercisesById[state.execiseId]!!
    val bodyWeightSets = exercise.sets.filterIsInstance<BodyWeightSet>()

    val totalReps = bodyWeightSets.sumOf { it.reps }
    val averageReps = if (bodyWeightSets.isNotEmpty()) totalReps / bodyWeightSets.size else 0.0

    val previousSet = state.previousSetData as BodyWeightSetData
    var currentSet by remember { mutableStateOf(state.currentSetData as BodyWeightSetData) }

    var isRepsInEditMode by remember { mutableStateOf(false) }

    var lastInteractionTime by remember { mutableLongStateOf(System.currentTimeMillis()) }

    val updateInteractionTime = {
        lastInteractionTime = System.currentTimeMillis()
    }

    LaunchedEffect(currentSet) {
        state.currentSetData = currentSet
    }

    LaunchedEffect(forceStopEditMode) {
        if(forceStopEditMode) isRepsInEditMode = false
    }

    LaunchedEffect(isRepsInEditMode) {
        if (isRepsInEditMode) {
            onEditModeEnabled()
            while (isRepsInEditMode) {
                if (System.currentTimeMillis() - lastInteractionTime > 5000) {
                    isRepsInEditMode = false
                }
                delay(1000) // Check every second
            }
        } else {
            onEditModeDisabled()
        }
    }

    fun onMinusClick(){
        updateInteractionTime()
        if (isRepsInEditMode && currentSet.actualReps>1){
            currentSet = currentSet.copy(
                actualReps = currentSet.actualReps-1
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
    }

    @Composable
    fun RepsRow(modifier: Modifier) {
        Row(
            modifier = modifier
                .combinedClickable(
                    onClick = {
                    },
                    onLongClick = {
                        if (!forceStopEditMode) {
                            isRepsInEditMode = !isRepsInEditMode
                            updateInteractionTime()
                        }

                        VibrateOnce(context)
                    },
                    onDoubleClick = {
                        if (isRepsInEditMode) {
                            currentSet = currentSet.copy(
                                actualReps = previousSet.actualReps
                            )
                            state.currentSetData = currentSet
                            VibrateTwice(context)
                        }
                    }
                ),
            verticalAlignment = Alignment.Bottom,
            horizontalArrangement = Arrangement.End
        ) {
            Text(
                text = "${currentSet.actualReps}",
                style = MaterialTheme.typography.display3,
                textAlign = TextAlign.End
            )
            Spacer(modifier = Modifier.width(5.dp))
            val label = if (currentSet.actualReps == 1) "rep" else "reps"
            Text(
                text = label,
                style = MaterialTheme.typography.caption3,
                modifier = Modifier.padding(bottom = 5.dp),
            )
        }
    }


    @Composable
    fun SetScreen(customModifier: Modifier) {
        Column(
            modifier = customModifier.padding(vertical = 10.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Row(
                modifier = Modifier.weight(2f),
                verticalAlignment = Alignment.Bottom,
                horizontalArrangement = Arrangement.Center
            ) {
                RepsRow(Modifier)
            }
            HorizontalDivider(modifier = Modifier.fillMaxWidth(), thickness = 1.dp)
            Row(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.Center )
            {
                TrendComponent(Modifier,"ΔVol:",currentSet.actualReps, averageReps)
            }
        }
    }

    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
        modifier = modifier.padding(horizontal = 15.dp)
    ){
        if (isRepsInEditMode) {
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
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.Center
                    ) {
                        RepsRow(Modifier)
                    }
                }
            )

        }else{
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
}