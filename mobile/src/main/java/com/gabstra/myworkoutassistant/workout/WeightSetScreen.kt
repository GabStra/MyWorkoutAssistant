package com.gabstra.myworkoutassistant.workout

import android.annotation.SuppressLint
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
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
import com.gabstra.myworkoutassistant.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlin.math.abs

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun WeightSetScreen(
    viewModel: WorkoutViewModel,
    hapticsViewModel: HapticsViewModel,
    modifier: Modifier,
    state: WorkoutState.Set,
    forceStopEditMode: Boolean,
    onEditModeEnabled: () -> Unit,
    onEditModeDisabled: () -> Unit,
    extraInfo: (@Composable (WorkoutState.Set) -> Unit)? = null,
    exerciseTitleComposable: @Composable () -> Unit,
    customComponentWrapper: @Composable (@Composable () -> Unit) -> Unit,
) {
    val context = LocalContext.current

    val previousSetData = state.previousSetData as WeightSetData
    var currentSetData by remember { mutableStateOf(state.currentSetData as WeightSetData) }

    val equipment = state.equipment
    val shouldLockCalibrationEdits = remember(state.isCalibrationSet) {
        state.isCalibrationSet
    }
    var availableWeights by remember(state.equipment) { mutableStateOf<Set<Double>>(emptySet()) }

    LaunchedEffect(equipment) {
        availableWeights = viewModel.getWeightByEquipment(equipment)
    }

    var closestWeight by remember(state.set.id) { mutableStateOf<Double?>(null) }
    var closestWeightIndex by remember(state.set.id) { mutableStateOf<Int?>(null) }
    var selectedWeightIndex by remember(state.set.id) { mutableStateOf<Int?>(null) }

    val cumulativeWeight = remember(currentSetData, equipment) {
        currentSetData.getWeight()
    }

    LaunchedEffect(availableWeights, cumulativeWeight) {
        withContext(Dispatchers.Default) {
            if (availableWeights.isEmpty()) return@withContext
            closestWeight = availableWeights.minByOrNull { abs(it - cumulativeWeight) }
            closestWeightIndex = availableWeights.indexOf(closestWeight)
            selectedWeightIndex = closestWeightIndex
        }
    }

    var isRepsInEditMode by remember { mutableStateOf(false) }
    var isWeightInEditMode by remember { mutableStateOf(false) }

    var lastInteractionTime by remember { mutableLongStateOf(System.currentTimeMillis()) }

    val updateInteractionTime = {
        lastInteractionTime = System.currentTimeMillis()
    }

    val isInEditMode = isRepsInEditMode || isWeightInEditMode

    val headerStyle = MaterialTheme.typography.titleSmall
    val typography = MaterialTheme.typography
    val itemStyle = remember(typography) { typography.displayLarge.copy(fontWeight = FontWeight.Bold) }

    LaunchedEffect(currentSetData) {
        state.currentSetData = currentSetData
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
            // Flush any pending plate recalculation when exiting edit mode
            viewModel.flushPlateRecalculation()
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

    LaunchedEffect(forceStopEditMode) {
        if (forceStopEditMode) {
            isRepsInEditMode = false
            isWeightInEditMode = false
        }
    }

    fun onMinusClick() {
        if (shouldLockCalibrationEdits) return
        updateInteractionTime()
        if (isRepsInEditMode && (currentSetData.actualReps > 1)) {
            val newRep = currentSetData.actualReps - 1

            val newSetData = currentSetData.copy(
                actualReps = newRep
            )

            currentSetData = currentSetData.copy(
                actualReps = newSetData.actualReps,
                volume = newSetData.calculateVolume()
            )

            hapticsViewModel.doGentleVibration()
        }
        if (isWeightInEditMode) {
            selectedWeightIndex?.let {
                if (it > 0) {
                    selectedWeightIndex = it - 1

                    val newSetData = currentSetData.copy(
                        actualWeight = availableWeights.elementAt(selectedWeightIndex!!)
                    )

                    currentSetData = currentSetData.copy(
                        actualWeight = newSetData.actualWeight,
                        volume = newSetData.calculateVolume()
                    )
                    
                    // Schedule debounced plate recalculation
                    viewModel.schedulePlateRecalculation(newSetData.actualWeight)
                }
            }

            hapticsViewModel.doGentleVibration()
        }

    }

    fun onPlusClick() {
        if (shouldLockCalibrationEdits) return
        updateInteractionTime()
        if (isRepsInEditMode) {
            val newRep = currentSetData.actualReps + 1

            val newSetData = currentSetData.copy(
                actualReps = newRep
            )

            currentSetData = currentSetData.copy(
                actualReps = newSetData.actualReps,
                volume = newSetData.calculateVolume()
            )

            hapticsViewModel.doGentleVibration()
        }
        if (isWeightInEditMode) {
            selectedWeightIndex?.let {
                if (it < availableWeights.size - 1) {
                    selectedWeightIndex = it + 1

                    val newSetData = currentSetData.copy(
                        actualWeight = availableWeights.elementAt(selectedWeightIndex!!)
                    )

                    currentSetData = currentSetData.copy(
                        actualWeight = newSetData.actualWeight,
                        volume = newSetData.calculateVolume()
                    )
                    
                    // Schedule debounced plate recalculation
                    viewModel.schedulePlateRecalculation(newSetData.actualWeight)
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
                    onClick = {
                    },
                    onLongClick = {
                        if (forceStopEditMode) return@combinedClickable
                        if (shouldLockCalibrationEdits) return@combinedClickable

                        isRepsInEditMode = !isRepsInEditMode
                        updateInteractionTime()
                        isWeightInEditMode = false

                        hapticsViewModel.doGentleVibration()
                    },
                    onDoubleClick = {
                        if (shouldLockCalibrationEdits) return@combinedClickable
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
            val textColor = when {
                currentSetData.actualReps == previousSetData.actualReps -> MaterialTheme.colorScheme.onBackground
                currentSetData.actualReps < previousSetData.actualReps -> MaterialTheme.colorScheme.error
                else -> MaterialTheme.colorScheme.secondary
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
                    onClick = {},
                    onLongClick = {
                        if (forceStopEditMode) return@combinedClickable
                        if (shouldLockCalibrationEdits) return@combinedClickable

                        isWeightInEditMode = !isWeightInEditMode
                        updateInteractionTime()
                        isRepsInEditMode = false

                        hapticsViewModel.doGentleVibration()
                    },
                    onDoubleClick = {
                        if (shouldLockCalibrationEdits) return@combinedClickable
                        if (isWeightInEditMode) {
                            val newSetData = currentSetData.copy(
                                actualWeight = previousSetData.actualWeight,
                            )

                            currentSetData = currentSetData.copy(
                                actualWeight = previousSetData.actualWeight,
                                volume = newSetData.calculateVolume()
                            )

                            hapticsViewModel.doHardVibrationTwice()
                        }
                    }
                ),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            val textColor = when {
                currentSetData.actualWeight == previousSetData.actualWeight -> MaterialTheme.colorScheme.onBackground
                currentSetData.actualWeight < previousSetData.actualWeight -> MaterialTheme.colorScheme.error
                else -> MaterialTheme.colorScheme.secondary
            }

            val weightText = equipment!!.formatWeight(currentSetData.getWeight())

            ScalableText(
                modifier = Modifier.fillMaxWidth(),
                text = weightText,
                style = style,
                color = textColor,
                textAlign = TextAlign.Center
            )
        }
    }

    @SuppressLint("DefaultLocale")
    @Composable
    fun SetScreen(customModifier: Modifier) {
        Column (
            modifier = customModifier,
            verticalArrangement = Arrangement.Center
        ){
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(5.dp)
            ) {
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(2.5.dp)
                ) {
                    Text(
                        text = "WEIGHT (KG)",
                        style = headerStyle,
                        textAlign = TextAlign.Center,
                        color =  MaterialTheme.colorScheme.onBackground,
                    )
                    WeightRow(modifier = Modifier.fillMaxWidth(), style = itemStyle)
                }

                Column(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(2.5.dp)
                ) {
                    Text(
                        text = "REPS",
                        style = headerStyle,
                        textAlign = TextAlign.Center,
                        color =  MaterialTheme.colorScheme.onBackground,
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
        ) {
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
                            if (isRepsInEditMode) RepsRow(modifier = Modifier.fillMaxWidth(), style = itemStyle)
                            if (isWeightInEditMode) WeightRow(modifier = Modifier.fillMaxWidth(), style = itemStyle)
                        }
                    }
                )

            } else {
                Column(
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    exerciseTitleComposable()

                    if (extraInfo != null) {
                        //HorizontalDivider(modifier = Modifier.fillMaxWidth(), thickness = 1.dp)
                        extraInfo(state)
                    }
                    SetScreen(customModifier = Modifier)
                }
            }
        }
    }
}

