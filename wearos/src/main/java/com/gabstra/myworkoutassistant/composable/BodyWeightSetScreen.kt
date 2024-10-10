package com.gabstra.myworkoutassistant.composable

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
import com.gabstra.myworkoutassistant.presentation.theme.MyColors
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
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
    extraInfo: (@Composable (WorkoutState.Set) -> Unit)? = null,
    exerciseTitleComposable:  @Composable () -> Unit,
) {
    val context = LocalContext.current

    val previousSet = state.previousSetData as BodyWeightSetData
    var currentSet by remember { mutableStateOf(state.currentSetData as BodyWeightSetData) }

    var bestTotalVolume by remember { mutableStateOf<Int?>(null) }

    val exercise = viewModel.exercisesById[state.execiseId]!!
    val sets = exercise.sets.filter { it !is RestSet }

    LaunchedEffect(state.execiseId) {
        bestTotalVolume = viewModel.getBestVolumeByExerciseId(state.execiseId)?.toInt()
    }

    val totalHistoricalSetDataList = remember {
        viewModel.getHistoricalSetsDataByExerciseId<BodyWeightSetData>(state.execiseId)
    }

    val lastTotalVolume = remember {
        totalHistoricalSetDataList.sumOf { it.actualReps }
    }

    val averageVolume = remember(bestTotalVolume) { if (bestTotalVolume!=null) (bestTotalVolume!! / sets.size).toDouble() else{
        if(lastTotalVolume > 0) (lastTotalVolume / totalHistoricalSetDataList.size).toDouble() else 0.0
    } }

    val historicalSetDataList = remember {
        viewModel.getHistoricalSetsDataByExerciseIdAndLowerOrder<BodyWeightSetData>(state.execiseId, state.order+1)
    }

    val previousVolumeUpToNow = remember {
        historicalSetDataList.sumOf { it.actualReps }
    }

    val executedSetDataList = remember {
        viewModel.getExecutedSetsDataByExerciseIdAndLowerOrder<BodyWeightSetData>(state.execiseId, state.order)
    }

    val executedVolume = remember {
        executedSetDataList.sumOf { it.actualReps }
    }

    val currentVolume = currentSet.actualReps

    val currentTotalVolume = currentVolume + executedVolume

    val volumeProgress = if (lastTotalVolume > 0) currentTotalVolume.toDouble() / lastTotalVolume.toDouble() else 0.0

    val bestVolumeProgress = if (bestTotalVolume != null && bestTotalVolume!! > 0) (currentTotalVolume / bestTotalVolume!!).toDouble() else 0.0

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
                style = MaterialTheme.typography.title1,
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
        Box(
            modifier = customModifier,
            contentAlignment = Alignment.Center
        ){
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center
            ) {
                RepsRow(Modifier)

                if(bestTotalVolume != null && bestTotalVolume!! > 0 && (currentTotalVolume >= lastTotalVolume || bestTotalVolume == lastTotalVolume) ) {
                    Spacer(modifier = Modifier.height(5.dp))
                    val progressColorBar = when {
                        currentTotalVolume < previousVolumeUpToNow -> MyColors.Red
                        currentTotalVolume == previousVolumeUpToNow -> MyColors.Orange
                        else -> MyColors.Green
                    }
                    TrendComponentProgressBar(Modifier.fillMaxWidth().padding(horizontal = 5.dp), "Best Vol:", bestVolumeProgress, progressColorBar)
                }else{
                    if(volumeProgress > 0) {
                        Spacer(modifier = Modifier.height(5.dp))
                        val progressColorBar = when {
                            currentTotalVolume < previousVolumeUpToNow -> MyColors.Red
                            currentTotalVolume == previousVolumeUpToNow -> MyColors.Orange
                            else -> MyColors.Green
                        }
                        TrendComponentProgressBar(Modifier.fillMaxWidth().padding(horizontal = 5.dp), "Tot Vol:", volumeProgress, progressColorBar)
                    }
                }

                if(averageVolume > 0) {
                    Spacer(modifier = Modifier.height(5.dp))
                    Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                        TrendComponent(Modifier, "Target:", currentVolume, averageVolume)
                    }
                }
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
            Column(
                modifier = Modifier.fillMaxSize().padding(top = 10.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(5.dp)
            ){
                exerciseTitleComposable()
                HorizontalDivider(modifier = Modifier.fillMaxWidth(), thickness = 1.dp)
                Column(
                    modifier = Modifier.weight(1f),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(5.dp)
                ) {
                    SetScreen(customModifier = Modifier)
                    if (extraInfo != null) {
                        HorizontalDivider(modifier = Modifier.fillMaxWidth(), thickness = 1.dp)
                        extraInfo(state)
                    }
                }
            }
        }
    }
}