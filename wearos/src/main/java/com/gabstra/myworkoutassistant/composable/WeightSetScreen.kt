package com.gabstra.myworkoutassistant.composable

import android.util.Log
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column

import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
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
import androidx.wear.compose.foundation.lazy.ScalingLazyColumn
import androidx.wear.compose.foundation.lazy.ScalingLazyListAnchorType
import androidx.wear.compose.foundation.lazy.ScalingLazyListState
import androidx.wear.compose.foundation.lazy.rememberScalingLazyListState
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.PositionIndicator
import androidx.wear.compose.material.Scaffold
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.VibrateGentle
import com.gabstra.myworkoutassistant.data.VibrateTwice
import com.gabstra.myworkoutassistant.data.WorkoutState
import com.gabstra.myworkoutassistant.data.calculateVolume
import com.gabstra.myworkoutassistant.presentation.theme.MyColors
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import kotlinx.coroutines.delay
import kotlin.math.roundToInt

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun WeightSetScreen (
    viewModel: AppViewModel,
    modifier: Modifier,
    state: WorkoutState.Set,
    forceStopEditMode: Boolean,
    onEditModeEnabled : () -> Unit,
    onEditModeDisabled: () -> Unit,
    extraInfo: (@Composable (WorkoutState.Set) -> Unit)? = null,
    exerciseTitleComposable:  @Composable () -> Unit,
){
    val context = LocalContext.current

    val previousSet = state.previousSetData as WeightSetData
    var currentSet by remember { mutableStateOf(state.currentSetData as WeightSetData) }

    var bestTotalVolume by remember { mutableDoubleStateOf(0.0) }

    LaunchedEffect(state.execiseId) {
        bestTotalVolume = viewModel.getBestVolumeByExerciseId(state.execiseId)
    }

    val totalHistoricalSetDataList = remember(state.execiseId) {
        viewModel.getHistoricalSetsDataByExerciseId<WeightSetData>(state.execiseId)
    }

    val cumulativePastVolumePerSet = remember(totalHistoricalSetDataList) {
        totalHistoricalSetDataList.runningFold(0.0) { acc, setData ->
            acc + calculateVolume(setData.actualWeight,setData.actualReps)
        }.drop(1)
    }

    val lastTotalVolume = remember(totalHistoricalSetDataList) {
        totalHistoricalSetDataList.sumOf { calculateVolume(it.actualWeight,it.actualReps).toDouble() }
    }

    val historicalSetDataList = remember(state.execiseId,state.set.id) {
        viewModel.getHistoricalSetsDataByExerciseIdAndTakeUntilSetId<WeightSetData>(state.execiseId, state.set.id)
    }

    val previousVolumeUpToNow = remember(historicalSetDataList) {
        historicalSetDataList.sumOf { calculateVolume(it.actualWeight,it.actualReps).toDouble() }
    }

    // Store the executed set data list
    val executedSetDataList = remember(state.execiseId,state.set.id) {
        viewModel.getExecutedSetsDataByExerciseIdAndTakeUntilSetId<WeightSetData>(state.execiseId, state.set.id)
    }

    val executedVolume = remember(executedSetDataList) {
        executedSetDataList.sumOf { calculateVolume(it.actualWeight, it.actualReps).toDouble() }
    }

    val currentVolume = calculateVolume(
        currentSet.actualWeight,
        currentSet.actualReps,
    )

    val currentTotalVolume = currentVolume + executedVolume

    val bestVolumeProgress = remember(bestTotalVolume, currentTotalVolume) {
        if (bestTotalVolume > 0) currentTotalVolume / bestTotalVolume else 0.0
    }

    var isRepsInEditMode by remember { mutableStateOf(false) }
    var isWeightInEditMode by remember { mutableStateOf(false) }

    var lastInteractionTime by remember { mutableLongStateOf(System.currentTimeMillis()) }

    val updateInteractionTime = {
        lastInteractionTime = System.currentTimeMillis()
    }

/*    val maxWeightSetData = historicalSetDataList.maxByOrNull { it.actualWeight }!!
    val minRepsMaxWeightSetData = historicalSetDataList.filter { it.actualWeight == maxWeightSetData.actualWeight }.minByOrNull { it.actualReps }!!
    val max1RM = getOneRepMax(minRepsMaxWeightSetData.actualWeight, minRepsMaxWeightSetData.actualReps)

    val current1RM = getOneRepMax(currentSet.actualWeight, currentSet.actualReps)*/

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

            VibrateGentle(context)
        }
        if (isWeightInEditMode && (currentSet.actualWeight > 0)){
            currentSet = currentSet.copy(
                actualWeight = currentSet.actualWeight.minus(0.25F)
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
        if (isWeightInEditMode){
            currentSet = currentSet.copy(
                actualWeight = currentSet.actualWeight.plus(0.25F)
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
                            isWeightInEditMode = false
                        }

                        VibrateGentle(context)
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
                horizontalArrangement = Arrangement.Center
            ) {
                val style = MaterialTheme.typography.body1.copy(fontSize = 20.sp)
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
    fun WeightRow(modifier: Modifier) {
            Row(
                modifier = modifier
                    .combinedClickable(
                        onClick = {
                        },
                        onLongClick = {
                            if (!forceStopEditMode) {
                                isWeightInEditMode = !isWeightInEditMode
                                updateInteractionTime()
                                isRepsInEditMode = false
                            }
                            VibrateGentle(context)
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
                horizontalArrangement = Arrangement.Center
            ) {
                val style = MaterialTheme.typography.body1.copy(fontSize = 20.sp)
                Text(
                    text = if (currentSet.actualWeight % 1 == 0f) {
                        "${currentSet.actualWeight.toInt()}"
                    } else {
                        "${currentSet.actualWeight}"
                    },
                    style = style,
                    textAlign = TextAlign.End
                )
                Spacer(modifier = Modifier.width(5.dp))
                Text(
                    text = "kg",
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

            val modifierToUse =  if(bestVolumeProgress > 0 && lastTotalVolume > 0) Modifier.weight(1f) else Modifier.fillMaxWidth()

            Row(
                modifier = modifierToUse,
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.Center
            ) {
                WeightRow(Modifier)
                Spacer(modifier = Modifier.width(5.dp))
                RepsRow(Modifier)
            }

            if(bestVolumeProgress > 0 && lastTotalVolume > 0){
                Spacer(modifier = Modifier.height(5.dp))
                val progressColorBar = when {
                    currentTotalVolume < previousVolumeUpToNow -> MyColors.Red
                    currentTotalVolume == previousVolumeUpToNow -> MyColors.Orange
                    else -> MyColors.Green
                }

                var markers = cumulativePastVolumePerSet.dropLast(1)
                    .filter { it != 0.0 }
                    .mapIndexed { index, it ->
                        MarkerData(
                            ratio = it / bestTotalVolume,
                            text = "${index + 1}",
                            color = Color.Black
                        )
                    }

                val ratio = if (previousVolumeUpToNow != 0.0) {
                    (currentTotalVolume - previousVolumeUpToNow) / previousVolumeUpToNow
                } else {
                    0.0
                }

                val displayText = when {
                    ratio >= 1 -> String.format("x%.2f", ratio+1).replace(',','.')
                    ratio >= 0.1 -> String.format("+%d%%", (ratio * 100).roundToInt())
                    ratio > 0 -> String.format("+%.1f%%", (ratio * 100)).replace(',','.').replace(".0","")
                    ratio <= -0.1 -> String.format("%d%%", (ratio * 100).roundToInt())
                    else -> String.format("%.1f%%", (ratio * 100)).replace(',','.').replace(".0","")
                }

                val indicatorMarker = if(ratio == 0.0) null else MarkerData(
                    ratio = bestVolumeProgress,
                    text = displayText,
                    color = Color.White,
                    textColor = if(ratio > 0) MyColors.Green else MyColors.Red
                )

                if(bestTotalVolume != lastTotalVolume){
                    markers = markers + MarkerData(
                        ratio = lastTotalVolume / bestTotalVolume,
                        text = "${cumulativePastVolumePerSet.size}",
                        color = Color.Black
                    )
                }

                TrendComponentProgressBarWithMarker(
                    modifier = Modifier.fillMaxWidth(),
                    label = "Best:",
                    ratio = bestVolumeProgress,
                    progressBarColor = progressColorBar,
                    markers = markers,
                    indicatorMarker = indicatorMarker
                )
            }
        }
    }

    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
        modifier = modifier.padding(horizontal = 15.dp)
    ){
        if (isRepsInEditMode || isWeightInEditMode) {
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
                        modifier = Modifier.height(40.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.Center
                    ) {
                        if (isRepsInEditMode) RepsRow(Modifier.fillMaxHeight())
                        if (isWeightInEditMode) WeightRow(Modifier.fillMaxHeight())
                    }
                }
            )

        }
        else
        {
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