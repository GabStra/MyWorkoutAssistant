package com.gabstra.myworkoutassistant.composable


import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column


import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.material3.Divider
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
import com.gabstra.myworkoutassistant.data.getOneRepMax
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import kotlinx.coroutines.delay

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun WeightSetScreen (
    viewModel: AppViewModel,
    modifier: Modifier,
    state: WorkoutState.Set,
    forceStopEditMode: Boolean,
    onEditModeEnabled : () -> Unit,
    onEditModeDisabled: () -> Unit,
    extraInfo: (@Composable (WorkoutState.Set) -> Unit)? = null
){
    val context = LocalContext.current

    val previousSet = state.previousSetData as WeightSetData
    var currentSet by remember { mutableStateOf(state.currentSetData as WeightSetData) }

    val historicalSetDataList = remember {
        val data = viewModel.getHistoricalSetsDataByExerciseId<WeightSetData>(state.execiseId)
        data.ifEmpty {
            viewModel.getAllExecutedSetsDataByExerciseId<WeightSetData>(state.execiseId)
        }
    }

    // Calculate the historical volume
    val historicalVolume = remember {
        historicalSetDataList.sumOf { calculateVolume(it.actualWeight, it.actualReps).toDouble() }
    }

    // Store the executed set data list
    val executedSetDataList = remember {
        viewModel.getExecutedSetsDataByExerciseIdAndLowerOrder<WeightSetData>(state.execiseId, state.order)
    }

    val executedVolume = remember {
        executedSetDataList.sumOf { calculateVolume(it.actualWeight, it.actualReps).toDouble() }
    }

    val averageVolume = remember { if (historicalSetDataList.isNotEmpty()) historicalVolume / historicalSetDataList.size else 0.0 }

    val currentVolume = calculateVolume(
        currentSet.actualWeight,
        currentSet.actualReps,
    )

    val currentTotalVolume = currentVolume + executedVolume

    val volumeProgress = if (historicalVolume > 0) currentTotalVolume / historicalVolume else 0.0

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

            VibrateOnce(context)
        }
        if (isWeightInEditMode && (currentSet.actualWeight > 0)){
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
                horizontalArrangement = Arrangement.spacedBy(5.dp)
            ) {
                Text(
                    text = "${currentSet.actualReps}",
                    style = MaterialTheme.typography.display3,
                    textAlign = TextAlign.End
                )
                val label = if (currentSet.actualReps == 1) "rep" else "reps"
                Text(
                    text = label,
                    style = MaterialTheme.typography.caption3,
                    modifier = Modifier.padding(bottom = 5.dp),
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
                    text = if (currentSet.actualWeight % 1 == 0f) {
                        "${currentSet.actualWeight.toInt()}"
                    } else {
                        "${currentSet.actualWeight}"
                    },
                    style = MaterialTheme.typography.display3,
                    textAlign = TextAlign.End
                )
                Spacer(modifier = Modifier.width(5.dp))
                Text(
                    text = "kg",
                    style = MaterialTheme.typography.caption3,
                    modifier = Modifier.padding(bottom = 5.dp),
                )
            }
        }
    }

    @Composable
    fun SetScreen(customModifier: Modifier) {
        Column(
            modifier = customModifier.padding(10.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Row(
                modifier = Modifier
                    .weight(2f)
                    .fillMaxWidth(),
                verticalAlignment = Alignment.Bottom,
                horizontalArrangement = Arrangement.Center
            ) {
                RepsRow(Modifier)
                Spacer(modifier = Modifier.width(5.dp))
                WeightRow(Modifier)
            }
            if(volumeProgress > 0) {
                TrendComponentProgressBar(
                    Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 5.dp), "Tot Vol:", volumeProgress)
            }
            Row(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.Center)
            {
                if(averageVolume > 0) {
                    TrendComponent(Modifier, "Target Vol:", currentVolume, averageVolume)
                }
                //Spacer(modifier = Modifier.width(5.dp))
                //TrendComponent(Modifier,"1RM:",current1RM, max1RM)
            }
        }
    }

    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
        modifier = modifier
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
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.Center
                    ) {
                        if (isRepsInEditMode) RepsRow(Modifier)
                        if (isWeightInEditMode) WeightRow(Modifier)
                    }
                }
            )

        }
        else
        {
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