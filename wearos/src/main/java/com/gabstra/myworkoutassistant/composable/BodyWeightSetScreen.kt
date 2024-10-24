package com.gabstra.myworkoutassistant.composable

import android.util.Log
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
import androidx.compose.material3.HorizontalDivider
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableDoubleStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.wear.compose.foundation.lazy.ScalingLazyListState
import androidx.wear.compose.foundation.lazy.rememberScalingLazyListState
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.VibrateGentle
import com.gabstra.myworkoutassistant.data.VibrateTwice
import com.gabstra.myworkoutassistant.data.WorkoutState
import com.gabstra.myworkoutassistant.presentation.theme.MyColors
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import kotlinx.coroutines.delay
import kotlin.math.roundToInt

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

    var bestTotalVolume by remember { mutableDoubleStateOf(0.0) }

    val exercise = remember(state.exerciseId) {
        viewModel.exercisesById[state.exerciseId]!!
    }

    val sets = remember(exercise) {
        exercise.sets.filter { it !is RestSet }
    }

    val setIndex = remember(state.set.id) {
        sets.indexOfFirst { it.id == state.set.id }
    }

    LaunchedEffect(state.exerciseId) {
        bestTotalVolume = viewModel.getBestVolumeByExerciseId(state.exerciseId)
    }

    val totalHistoricalSetDataList = remember(state.exerciseId) {
        viewModel.getHistoricalSetsDataByExerciseId<BodyWeightSetData>(state.exerciseId)
    }

    val cumulativePastVolumePerSet = remember(totalHistoricalSetDataList) {
        totalHistoricalSetDataList.runningFold(0.0) { acc, setData ->
            acc + setData.actualReps.toDouble()
        }.drop(1)
    }

    val lastTotalVolume = remember(totalHistoricalSetDataList) {
        totalHistoricalSetDataList.sumOf { it.actualReps }.toDouble()
    }

    val historicalSetDataList = remember(state.exerciseId,state.set.id) {
        viewModel.getHistoricalSetsDataByExerciseIdAndTakeUntilSetId<BodyWeightSetData>(state.exerciseId, state.set.id)
    }

    val previousVolumeUpToNow = remember(historicalSetDataList) {
        historicalSetDataList.sumOf { it.actualReps }
    }

    val executedSetDataList = remember(state.exerciseId,state.set.id) {
        viewModel.getExecutedSetsDataByExerciseIdAndTakeUntilSetId<BodyWeightSetData>(state.exerciseId, state.set.id)
    }

    val executedVolume = remember(executedSetDataList) {
        executedSetDataList.sumOf { it.actualReps }
    }

    val currentVolume = currentSet.actualReps

    val currentTotalVolume = currentVolume + executedVolume

    val bestVolumeProgress = remember(bestTotalVolume,currentTotalVolume) {
        if (bestTotalVolume != 0.0) currentTotalVolume.toDouble() / bestTotalVolume else 0.0
    }

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

            VibrateGentle(context)
        }
    }

    fun onPlusClick(){
        updateInteractionTime()
        if (isRepsInEditMode){
            currentSet = currentSet.copy(
                actualReps = currentSet.actualReps+1
            )

            VibrateGentle(context)
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

                        VibrateGentle(context)
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
            horizontalArrangement = Arrangement.Center
        ) {
            Row(
                verticalAlignment = Alignment.Bottom,
                horizontalArrangement = Arrangement.Center
            ) {
                val style = MaterialTheme.typography.body1.copy(fontSize = 24.sp)
                Text(
                    text = "${currentSet.actualReps}",
                    style = style,
                    textAlign = TextAlign.End
                )
                Spacer(modifier = Modifier.width(5.dp))
                val label = if (currentSet.actualReps == 1) "rep" else "reps"
                Text(
                    text = label,
                    style = style.copy(fontSize = style.fontSize * 0.39f),
                    modifier = Modifier.padding(bottom = 2.dp)
                )
            }
        }
    }


    @Composable
    fun SetScreen(customModifier: Modifier) {
        Column(
            modifier = customModifier,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            RepsRow(Modifier)
            if (bestVolumeProgress > 0) {
                Spacer(modifier = Modifier.height(5.dp))
                val progressColorBar = when {
                    currentTotalVolume < previousVolumeUpToNow -> MyColors.Red
                    currentTotalVolume == previousVolumeUpToNow -> MyColors.Orange
                    else -> MyColors.Green
                }


                val markers = mutableListOf<MarkerData>()

                val marker = cumulativePastVolumePerSet.getOrNull(setIndex)?.let {
                    MarkerData(
                        ratio = it / bestTotalVolume,
                        text = "${setIndex + 1}",
                        color = Color.Black
                    )
                }
                if(marker != null && marker.ratio < 1){
                    markers.add(marker)
                }

                val ratio = if (previousVolumeUpToNow.toDouble() != 0.0) {
                    (currentTotalVolume.toDouble() - previousVolumeUpToNow.toDouble()) / previousVolumeUpToNow.toDouble()
                } else {
                    0.0
                }

                val displayText = when {
                    ratio >= 1 -> String.format("x%.2f", ratio + 1).replace(',', '.')
                    ratio >= 0.1 -> String.format("+%d%%", (ratio * 100).roundToInt())
                    ratio > 0 -> String.format("+%.1f%%", (ratio * 100)).replace(',', '.')
                        .replace(".0", "")

                    ratio <= -0.1 -> String.format("%d%%", (ratio * 100).roundToInt())
                    else -> String.format("%.1f%%", (ratio * 100)).replace(',', '.')
                        .replace(".0", "")
                }

                val indicatorMarker =
                    if (ratio == 0.0) null else MarkerData(
                        ratio = bestVolumeProgress,
                        text = displayText,
                        color = Color.White,
                        textColor = if (ratio > 0) MyColors.Green else MyColors.Red
                    )

               /* if (bestTotalVolume != lastTotalVolume) {
                    markers = markers + MarkerData(
                        ratio = lastTotalVolume / bestTotalVolume,
                        text = "${cumulativePastVolumePerSet.size}",
                        color = Color.Black
                    )
                }*/

                TrendComponentProgressBarWithMarker(
                    modifier = Modifier.fillMaxWidth(),
                    label = "Vol:",
                    ratio = bestVolumeProgress,
                    progressBarColor = progressColorBar,
                    indicatorMarker = indicatorMarker,
                    markers = markers
                )
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
                modifier = Modifier
                    .fillMaxSize()
                    .padding(top = 10.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center
            ){
                Column(
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(5.dp)
                ) {
                    exerciseTitleComposable()
                    HorizontalDivider(modifier = Modifier.fillMaxWidth(), thickness = 1.dp)
                    SetScreen(customModifier = Modifier.weight(1f))
                    if (extraInfo != null) {
                        HorizontalDivider(modifier = Modifier.fillMaxWidth(), thickness = 1.dp)
                        extraInfo(state)
                    }
                }
            }
        }
    }
}