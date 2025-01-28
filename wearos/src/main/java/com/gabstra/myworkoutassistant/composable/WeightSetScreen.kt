package com.gabstra.myworkoutassistant.composable

import android.annotation.SuppressLint
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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
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
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.VibrateGentle
import com.gabstra.myworkoutassistant.data.VibrateTwice
import com.gabstra.myworkoutassistant.data.WorkoutState
import com.gabstra.myworkoutassistant.presentation.theme.MyColors
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
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

    val previousSetData = state.previousSetData as WeightSetData
    var currentSetData by remember { mutableStateOf(state.currentSetData as WeightSetData) }

    val isLastSet = remember(state) {
        viewModel.setsByExerciseId[state.exerciseId]!!.last() == state
    }

    val exercise = remember(state.exerciseId) {
        viewModel.exercisesById[state.exerciseId]!!
    }

    val equipment = remember(exercise) {
        exercise.equipmentId?.let { viewModel.getEquipmentById(it) }
    }

    var availableWeights by remember(exercise) { mutableStateOf<Set<Double>>(emptySet()) }

    LaunchedEffect(equipment) {
        availableWeights = viewModel.getWeightByEquipment(equipment)
    }

    val equipmentVolumeMultiplier = remember(equipment) {
        equipment?.volumeMultiplier ?: 1.0
    }

    var closestWeight by remember(state.set.id) { mutableStateOf<Double?>(null) }
    var closestWeightIndex by remember(state.set.id) { mutableStateOf<Int?>(null) }
    var selectedWeightIndex by remember(state.set.id) { mutableStateOf<Int?>(null) }

    val cumulativeWeight = remember(currentSetData,equipment){
        currentSetData.getWeight(equipment)
    }

    LaunchedEffect(availableWeights,cumulativeWeight) {
        withContext(Dispatchers.Default) {
            if(availableWeights.isEmpty()) return@withContext
            closestWeight = availableWeights.minByOrNull { kotlin.math.abs(it - cumulativeWeight) }
            closestWeightIndex = availableWeights.indexOf(closestWeight)
            selectedWeightIndex = closestWeightIndex
        }
    }

    val executedVolume = remember(state.exerciseId,state.set.id) {
        val executedSetDataList = viewModel.getExecutedSetsDataByExerciseIdAndTakePriorToSetId<WeightSetData>(state.exerciseId, state.set.id)
        executedSetDataList.sumOf { it.volume}
    }

    val executedVolumeProgression by remember {
        derivedStateOf {
            if (state.exerciseOriginalVolume != 0.0) {
                executedVolume / state.exerciseOriginalVolume
            } else 0.0
        }
    }

    val currentTotalVolume by remember {
        derivedStateOf {
            currentSetData.volume + executedVolume
        }
    }

    val previousTotalVolume by remember {
        derivedStateOf {
            previousSetData.volume + executedVolume
        }
    }

    val volumeProgression by remember {
        derivedStateOf {
            if (state.exerciseOriginalVolume != 0.0) {
                currentTotalVolume / state.exerciseOriginalVolume
            } else 0.0
        }
    }

    var isRepsInEditMode by remember { mutableStateOf(false) }
    var isWeightInEditMode by remember { mutableStateOf(false) }

    var lastInteractionTime by remember { mutableLongStateOf(System.currentTimeMillis()) }

    val updateInteractionTime = {
        lastInteractionTime = System.currentTimeMillis()
    }

    val isInEditMode = isRepsInEditMode || isWeightInEditMode

    LaunchedEffect(currentSetData) {
        state.currentSetData = currentSetData
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
        if (isRepsInEditMode && (currentSetData.actualReps > 1)){
            val newSetData = currentSetData.copy(
                actualReps = currentSetData.actualReps-1
            )

            currentSetData = currentSetData.copy(
                actualReps = newSetData.actualReps,
                volume = newSetData.calculateVolume(equipment)
            )

            VibrateGentle(context)
        }
        if (isWeightInEditMode ){
            selectedWeightIndex?.let {
                if (it > 0) {
                    selectedWeightIndex = it - 1

                    val newActualWeight = if(equipment is Barbell){
                        (availableWeights!!.elementAt(selectedWeightIndex!!) - equipment.barWeight) / equipmentVolumeMultiplier
                    }else{
                        availableWeights!!.elementAt(selectedWeightIndex!!)/ equipmentVolumeMultiplier
                    }

                    val newSetData = currentSetData.copy(
                        actualWeight = newActualWeight
                    )

                    currentSetData = currentSetData.copy(
                        actualWeight = newSetData.actualWeight,
                        volume = newSetData.calculateVolume(equipment)
                    )
                }
            }

            VibrateGentle(context)
        }

    }

    fun onPlusClick(){
        updateInteractionTime()
        if (isRepsInEditMode){
            val newSetData = currentSetData.copy(
                actualReps = currentSetData.actualReps+1
            )

            currentSetData = currentSetData.copy(
                actualReps = newSetData.actualReps,
                volume = newSetData.calculateVolume(equipment)
            )

            VibrateGentle(context)
        }
        if (isWeightInEditMode){
            selectedWeightIndex?.let {
                if (it < availableWeights!!.size - 1) {
                    selectedWeightIndex = it + 1

                    val newActualWeight = if(equipment is Barbell){
                        (availableWeights.elementAt(selectedWeightIndex!!) - equipment.barWeight) / equipmentVolumeMultiplier
                    }else{
                        availableWeights.elementAt(selectedWeightIndex!!)/ equipmentVolumeMultiplier
                    }

                    val newSetData = currentSetData.copy(
                        actualWeight = newActualWeight
                    )

                    currentSetData = currentSetData.copy(
                        actualWeight = newSetData.actualWeight,
                        volume = newSetData.calculateVolume(equipment)
                    )
                }
            }

            VibrateGentle(context)
        }
    }

    @Composable
    fun RepsRow(modifier: Modifier, showRepsLabel:Boolean = false) {
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
                            val newSetData = currentSetData.copy(
                                actualReps = previousSetData.actualReps,
                            )

                            currentSetData = currentSetData.copy(
                                actualReps = newSetData.actualReps,
                                volume = newSetData.calculateVolume(equipment)
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
                val textColor  = when {
                    currentSetData.actualReps == previousSetData.actualReps -> Color.Unspecified
                    currentSetData.actualReps < previousSetData.actualReps  -> MyColors.Red
                    else -> MyColors.Green
                }

                Text(
                    text = "${currentSetData.actualReps}",
                    style = style,
                    color = textColor,
                    textAlign = TextAlign.End
                )
                if(showRepsLabel){
                    Spacer(modifier = Modifier.width(3.dp))
                    val label = if (currentSetData.actualReps == 1) "rep" else "reps"
                    Text(
                        text = label,
                        style = style.copy(fontSize = style.fontSize * 0.5),
                        modifier = Modifier.padding(bottom = 2.dp),
                        color = textColor,
                    )
                }
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
                                val newSetData = currentSetData.copy(
                                    actualWeight = previousSetData.actualWeight,
                                )

                                currentSetData = currentSetData.copy(
                                    actualWeight = previousSetData.actualWeight,
                                    volume = newSetData.calculateVolume(equipment)
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
                val weight = currentSetData.actualWeight

                val textColor = when {
                    currentSetData.actualWeight == previousSetData.actualWeight -> Color.Unspecified
                    currentSetData.actualWeight < previousSetData.actualWeight  -> MyColors.Red
                    else -> MyColors.Green
                }

                Text(
                    text = if (weight % 1 == 0.0) {
                        "${weight.toInt()}"
                    } else {
                        "$weight"
                    },
                    style = style,
                    color =  textColor,
                    textAlign = TextAlign.End
                )
                Spacer(modifier = Modifier.width(3.dp))
                Text(
                    text = "kg",
                    style = style.copy(fontSize = style.fontSize * 0.5f),
                    modifier = Modifier.padding(bottom = 2.dp),
                    color =  textColor,
                )
            }
        }
    }

    @SuppressLint("DefaultLocale")
    @Composable
    fun SetScreen(customModifier: Modifier) {
        val style = MaterialTheme.typography.body1.copy(fontSize = 20.sp)

        Column(
            modifier = customModifier,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Row(
                modifier =  Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.Center
            ) {
                WeightRow(Modifier)
                Spacer(modifier = Modifier.width(5.dp))
                Text(
                    text = "x",
                    style = style.copy(fontSize = style.fontSize * 0.625f),
                    textAlign = TextAlign.Center
                )
                Spacer(modifier = Modifier.width(5.dp))
                RepsRow(Modifier)
            }

            val indicatorStyle = MaterialTheme.typography.body2

            if(volumeProgression > 0){
                Spacer(modifier = Modifier.height(10.dp))

                val progressBarColor = when {
                    currentTotalVolume.roundToInt() < previousTotalVolume.roundToInt() -> MyColors.Red
                    currentTotalVolume.roundToInt() > previousTotalVolume.roundToInt() -> MyColors.Green
                    else -> Color.White
                }

                ProgressIndicator(
                    modifier = Modifier.fillMaxWidth(),
                    ratio = volumeProgression,
                    previousRatio = executedVolumeProgression,
                    progressBarColor = progressBarColor,
                    showRatio = isLastSet,
                    expectedProgress = state.progressionValue
                )

                Spacer(modifier = Modifier.height(5.dp))

                Column(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(5.dp)
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically,horizontalArrangement = Arrangement.spacedBy(5.dp)){
                        if(state.streak > 0){
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Icon(
                                    Icons.Filled.Star,
                                    contentDescription = "Streak",
                                    tint = Color(0xFFFFD700)
                                )
                                Spacer(modifier = Modifier.width(3.dp))
                                Text(
                                    text = state.streak.toString(),
                                    style = indicatorStyle,
                                )
                            }
                        }
                    }
                }
            }
            if(state.isDeloading){
                Spacer(modifier = Modifier.height(10.dp))
                Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically){
                    Text(
                        text = "DELOAD",
                        style = indicatorStyle,
                        textAlign = TextAlign.Center,
                    )
                }
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
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.Center
                    ) {
                        if (isRepsInEditMode) RepsRow(Modifier, showRepsLabel = true)
                        if (isWeightInEditMode) WeightRow(Modifier)
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