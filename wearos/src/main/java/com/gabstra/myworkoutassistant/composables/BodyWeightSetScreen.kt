package com.gabstra.myworkoutassistant.composables

import android.annotation.SuppressLint
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.LightGray
import com.gabstra.myworkoutassistant.shared.Red
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun BodyWeightSetScreen(
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    modifier: Modifier,
    state: WorkoutState.Set,
    forceStopEditMode: Boolean,
    onEditModeEnabled : () -> Unit,
    onEditModeDisabled: () -> Unit,
    extraInfo: (@Composable (WorkoutState.Set) -> Unit)? = null,
    exerciseTitleComposable:  @Composable () -> Unit,
    customComponentWrapper: @Composable (@Composable () -> Unit) -> Unit,
) {
    val context = LocalContext.current

    val previousSetData = state.previousSetData as BodyWeightSetData
    var currentSetData by remember { mutableStateOf(state.currentSetData as BodyWeightSetData) }

    val exercise = remember(state.exerciseId) {
        viewModel.exercisesById[state.exerciseId]!!
    }

    val equipment = state.equipment
    var availableWeights by remember(state.equipment) { mutableStateOf<Set<Double>>(emptySet()) }

    var closestWeight by remember(state.set.id) { mutableStateOf<Double?>(null) }
    var closestWeightIndex by remember(state.set.id) { mutableStateOf<Int?>(null) }
    var selectedWeightIndex by remember(state.set.id) { mutableStateOf<Int?>(null) }

    LaunchedEffect(equipment) {
        availableWeights = if (equipment == null) {
            emptySet()
        }else{
            (viewModel.getWeightByEquipment(equipment) + setOf(0.0)).sorted().toSet()
        }
    }

    val cumulativeWeight = remember(currentSetData,equipment){
        currentSetData.getWeight() - currentSetData.relativeBodyWeightInKg
    }

   LaunchedEffect(availableWeights,cumulativeWeight) {
        withContext(Dispatchers.Default) {
            if(availableWeights.isEmpty()) return@withContext
            closestWeight = availableWeights.minByOrNull { kotlin.math.abs(it - cumulativeWeight) }
            closestWeightIndex = availableWeights.indexOf(closestWeight)
            selectedWeightIndex = closestWeightIndex
        }

    }

    var lastInteractionTime by remember { mutableLongStateOf(System.currentTimeMillis()) }

    val updateInteractionTime = {
        lastInteractionTime = System.currentTimeMillis()
    }

    var isRepsInEditMode by remember { mutableStateOf(false) }
    var isWeightInEditMode by remember { mutableStateOf(false) }

    val isInEditMode = isRepsInEditMode || isWeightInEditMode

    val typography = MaterialTheme.typography
    val headerStyle = remember(typography) { typography.body1.copy(fontSize = typography.body1.fontSize * 0.625f) }
    val itemStyle = remember(typography)  { typography.body1.copy(fontSize = typography.body1.fontSize * 1.625f, fontWeight = FontWeight.Bold) }

    LaunchedEffect(currentSetData) {
        state.currentSetData = currentSetData
    }

    LaunchedEffect(forceStopEditMode) {
        if(forceStopEditMode){
            isRepsInEditMode = false
            isWeightInEditMode = false
        }
    }

    LaunchedEffect(isInEditMode) {
        if (isInEditMode) {
            onEditModeEnabled()
            while (isInEditMode) {
                if (System.currentTimeMillis() - lastInteractionTime > 2000) {
                    isRepsInEditMode = false
                    isWeightInEditMode = false
                }
                delay(1000) // Check every second
            }
        } else {
            onEditModeDisabled()
        }
    }

    var openDialogJob by remember { mutableStateOf<Job?>(null) }
    val coroutineScope = rememberCoroutineScope()

    var showWeightInfoDialog by remember { mutableStateOf(false) }

    fun startOpenDialogJob() {
        if( openDialogJob?.isActive == true) return
        openDialogJob?.cancel()
        openDialogJob = coroutineScope.launch {
            showWeightInfoDialog = true
            delay(5000L)
            showWeightInfoDialog = false
        }
    }

    val previousTotalVolume = remember(exercise.id, equipment) {
        viewModel.getAllSetHistoriesByExerciseId(exercise.id)
            .filter { it.setData is BodyWeightSetData }
            .map{ it.setData as BodyWeightSetData }
            .sumOf { it.calculateVolume()}
    }

    val executedVolume = remember(exercise.id, equipment, currentSetData, state ) {
        viewModel.getAllExecutedSetsByExerciseId(exercise.id)
            .filter { it.setData is BodyWeightSetData  && it.setId != state.set.id }
            .map{ it.setData as BodyWeightSetData }
            .sumOf { it.calculateVolume()} + currentSetData.calculateVolume()
    }

    fun onMinusClick(){
        updateInteractionTime()
        if (isRepsInEditMode && currentSetData.actualReps>1){
            val newSetData = currentSetData.copy(
                actualReps = currentSetData.actualReps-1
            )

            currentSetData = currentSetData.copy(
                actualReps = newSetData.actualReps,
                volume = newSetData.calculateVolume()
            )

            hapticsViewModel.doGentleVibration()
        }
        if (isWeightInEditMode ){
            selectedWeightIndex?.let {
                if (it > 0) {
                    selectedWeightIndex = it - 1

                    val newSetData = currentSetData.copy(
                        additionalWeight = availableWeights.elementAt(selectedWeightIndex!!)
                    )

                    currentSetData = currentSetData.copy(
                        additionalWeight = newSetData.additionalWeight,
                        volume = newSetData.calculateVolume()
                    )
                }
            }

            hapticsViewModel.doGentleVibration()
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
                volume = newSetData.calculateVolume()
            )

            hapticsViewModel.doGentleVibration()
        }
        if (isWeightInEditMode){
            selectedWeightIndex?.let {
                if (it < availableWeights.size - 1) {
                    selectedWeightIndex = it + 1

                    val newSetData = currentSetData.copy(
                        additionalWeight = availableWeights.elementAt(selectedWeightIndex!!)
                    )

                    currentSetData = currentSetData.copy(
                        additionalWeight = newSetData.additionalWeight,
                        volume = newSetData.calculateVolume()
                    )
                }
            }

            hapticsViewModel.doGentleVibration()
        }
    }

    @Composable
    fun RepsRow(modifier: Modifier = Modifier, style: TextStyle) {
        Row(
            modifier = modifier
                .combinedClickable(
                    onClick = {},
                    onLongClick = {
                        if (forceStopEditMode) return@combinedClickable

                        isRepsInEditMode = !isRepsInEditMode
                        updateInteractionTime()
                        isWeightInEditMode = false

                        hapticsViewModel.doGentleVibration()
                    },
                    onDoubleClick = {
                        if (isRepsInEditMode) {
                            val newSetData = currentSetData.copy(
                                actualReps = previousSetData.actualReps,
                            )

                            currentSetData = currentSetData.copy(
                                actualReps = newSetData.actualReps,
                                volume = newSetData.calculateVolume()
                            )

                            hapticsViewModel.doHardVibrationTwice()
                        }
                    }
                ),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            val textColor  = when {
                currentSetData.actualReps == previousSetData.actualReps -> LightGray
                currentSetData.actualReps < previousSetData.actualReps  -> Red
                else -> Green
            }

            ScalableText(
                modifier = Modifier.fillMaxWidth(),
                text = "${currentSetData.actualReps}",
                style = style,
                color = textColor,
                textAlign = TextAlign.Center
            )
        }
    }

    @Composable
    fun WeightRow(modifier: Modifier = Modifier, style: TextStyle) {
        Row(
            modifier = modifier
                .combinedClickable(
                    onClick = {
                    },
                    onLongClick = {
                        if (forceStopEditMode) return@combinedClickable

                        isWeightInEditMode = !isWeightInEditMode
                        updateInteractionTime()
                        isRepsInEditMode = false

                        hapticsViewModel.doGentleVibration()
                    },
                    onDoubleClick = {
                        if (isWeightInEditMode) {
                            val newSetData = currentSetData.copy(
                                additionalWeight = previousSetData.additionalWeight,
                            )

                            currentSetData = currentSetData.copy(
                                additionalWeight = previousSetData.additionalWeight,
                                volume = newSetData.calculateVolume()
                            )

                            hapticsViewModel.doHardVibrationTwice()
                        }
                    }
                ),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            val textColor = when {
                currentSetData.additionalWeight == previousSetData.additionalWeight -> LightGray
                currentSetData.additionalWeight < previousSetData.additionalWeight  -> Red
                else -> Green
            }

            val weightText = equipment!!.formatWeight(currentSetData.additionalWeight)

            ScalableText(
                modifier = Modifier.fillMaxWidth(),
                text = weightText,
                style = style,
                color =  textColor,
                textAlign = TextAlign.Center
            )
        }
    }

    @SuppressLint("DefaultLocale")
    @Composable
    fun SetScreen(customModifier: Modifier) {
        Column (
            modifier = customModifier.padding(vertical = 5.dp),
        ){
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(5.dp)
            ) {
                if(availableWeights.isNotEmpty() && currentSetData.additionalWeight != 0.0) {
                    Column(
                        modifier = Modifier.fillMaxWidth().weight(1f),
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.spacedBy(2.5.dp)
                    ) {
                        Text(
                            text = "WEIGHT (KG)",
                            style = headerStyle,
                            textAlign = TextAlign.Center,
                            color = LightGray,
                        )
                        WeightRow(modifier = Modifier.fillMaxWidth(), style = itemStyle)
                    }
                }
                Column(
                    modifier = Modifier.fillMaxWidth().weight(1f),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(2.5.dp)
                ) {
                    Text(
                        text = "REPS",
                        style = headerStyle,
                        textAlign = TextAlign.Center,
                        color =  LightGray,
                    )
                    RepsRow(modifier = Modifier.fillMaxWidth(), style = itemStyle)
                }
            }
        }
    }

    customComponentWrapper {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
            modifier = modifier
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
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.Center
                        ) {
                            if (isRepsInEditMode) RepsRow(Modifier, style = itemStyle)
                            if (isWeightInEditMode) WeightRow(Modifier, style = itemStyle)
                        }
                    }
                )

            }else{
                Column(
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(5.dp)
                ) {
                    exerciseTitleComposable()
                    if (extraInfo != null) {
                        //HorizontalDivider(modifier = Modifier.fillMaxWidth(), thickness = 1.dp)
                        extraInfo(state)
                    }
                    SetScreen(
                        customModifier = Modifier
                        .weight(1f)
                    )
                }
            }
        }
    }

}