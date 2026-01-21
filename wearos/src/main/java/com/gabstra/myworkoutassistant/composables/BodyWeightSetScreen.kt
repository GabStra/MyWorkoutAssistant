package com.gabstra.myworkoutassistant.composables

import android.annotation.SuppressLint
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
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Warning
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.onClick
import androidx.compose.ui.semantics.onLongClick
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.Icon
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.Red
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.viewmodels.CalibrationStep
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import java.time.Duration
import java.time.LocalDateTime
import java.time.temporal.ChronoUnit

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
    var currentSetData by remember(state.set.id, (state.set as? BodyWeightSet)?.additionalWeight) {
        mutableStateOf(state.currentSetData as BodyWeightSetData)
    }

    val exercise = remember(state.exerciseId) {
        viewModel.exercisesById[state.exerciseId]!!
    }
    
    val isCalibrationSet = remember(state.set) {
        (state.set as? BodyWeightSet)?.subCategory == SetSubCategory.CalibrationSet
    }
    val calibrationStep = state.calibrationStep
    
    // Only show calibration flow if equipment is present
    val shouldShowCalibration = isCalibrationSet && state.equipment != null

    val plateauReason = remember(state.exerciseId) {
        viewModel.plateauReasonByExerciseId[state.exerciseId]
    }
    val isPlateauDetected = plateauReason != null

    var showPlateauDialog by remember { mutableStateOf(false) }

    var showRed by remember { mutableStateOf(true) }

    LaunchedEffect(isPlateauDetected) {
        if (isPlateauDetected) {
            while (true) {
                val now = LocalDateTime.now()
                val truncated = now.truncatedTo(ChronoUnit.SECONDS)
                val nanoOfSecond = now.nano
                val nextHalfSecond = if (nanoOfSecond < 500_000_000) {
                    truncated.plusNanos(500_000_000)
                } else {
                    truncated.plusSeconds(1)
                }
                delay(Duration.between(now, nextHalfSecond).toMillis())
                showRed = !showRed
            }
        }
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
    val headerStyle = MaterialTheme.typography.bodyExtraSmall
    val itemStyle = remember(typography) { typography.numeralSmall.copy(fontWeight = FontWeight.Medium) }

    // Sync state.set.additionalWeight to local currentSetData when set weight changes
    // This ensures weights updated after RIR calibration are reflected in the UI
    LaunchedEffect(state.set.id, (state.set as? BodyWeightSet)?.additionalWeight) {
        val bodyWeightSet = state.set as? BodyWeightSet
        if (bodyWeightSet != null && bodyWeightSet.additionalWeight != currentSetData.additionalWeight) {
            // Update additionalWeight to match the set's weight and recalculate volume
            val updatedSetData = currentSetData.copy(additionalWeight = bodyWeightSet.additionalWeight)
            val finalSetData = updatedSetData.copy(volume = updatedSetData.calculateVolume())
            currentSetData = finalSetData
            // Also update state.currentSetData to keep it in sync
            state.currentSetData = finalSetData
        }
    }

    LaunchedEffect(currentSetData) {
        state.currentSetData = currentSetData
    }

    LaunchedEffect(forceStopEditMode) {
        if(forceStopEditMode){
            isRepsInEditMode = false
            isWeightInEditMode = false
        }
    }

    // Close edit modes when entering load selection step
    LaunchedEffect(calibrationStep) {
        if (calibrationStep == CalibrationStep.LoadSelection) {
            isRepsInEditMode = false
            isWeightInEditMode = false
        }
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
            // Flush any pending plate recalculation when exiting edit mode
            viewModel.flushPlateRecalculation()
            onEditModeDisabled()
        }
    }

    fun onMinusClick(){
        updateInteractionTime()
        if (isRepsInEditMode && currentSetData.actualReps>1){
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
                    
                    // Schedule debounced plate recalculation
                    // For BodyWeightSet, total weight = relativeBodyWeight + additionalWeight
                    viewModel.schedulePlateRecalculation(newSetData.getWeight())
                }
            }

            hapticsViewModel.doGentleVibration()
        }
    }

    fun onPlusClick(){
        updateInteractionTime()
        if (isRepsInEditMode){
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
                    
                    // Schedule debounced plate recalculation
                    // For BodyWeightSet, total weight = relativeBodyWeight + additionalWeight
                    viewModel.schedulePlateRecalculation(newSetData.getWeight())
                }
            }

            hapticsViewModel.doGentleVibration()
        }
    }

    @Composable
    fun RepsRow(modifier: Modifier = Modifier, style: TextStyle) {
        val repsText = "${currentSetData.actualReps}"
        fun toggleRepsEditMode() {
            if (forceStopEditMode) return
            // Disable edit mode on Step 2 (SetExecution)
            if (calibrationStep == CalibrationStep.SetExecution) return
            isRepsInEditMode = !isRepsInEditMode
            updateInteractionTime()
            isWeightInEditMode = false

            hapticsViewModel.doGentleVibration()
        }
        Row(
            modifier = modifier
                .height(40.dp)
                .combinedClickable(
                    onClick = {
                        updateInteractionTime()
                    },
                    onLongClick = {
                        toggleRepsEditMode()
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
                )
                .semantics(mergeDescendants = true) {
                    contentDescription = "${SetValueSemantics.RepsValueDescription}: $repsText"
                    role = Role.Button
                    onClick(
                        label = "Focus reps"
                    ) {
                        updateInteractionTime()
                        true
                    }
                    onLongClick(
                        label = "Edit reps"
                    ) {
                        toggleRepsEditMode()
                        true
                    }
                },
            verticalAlignment = Alignment.CenterVertically,
        ) {
            val textColor  = when {
                currentSetData.actualReps == previousSetData.actualReps -> MaterialTheme.colorScheme.onBackground
                currentSetData.actualReps < previousSetData.actualReps  -> Red
                else -> Green
            }

            ScalableText(
                modifier = Modifier.fillMaxWidth(),
                text = repsText,
                style = style,
                color = textColor,
                textAlign = TextAlign.Center
            )
        }
    }

    @Composable
    fun WeightRow(modifier: Modifier = Modifier, style: TextStyle) {
        val weightText = if (currentSetData.additionalWeight != 0.0) {
            equipment!!.formatWeight(currentSetData.additionalWeight)
        } else {
            "BW"
        }
        fun toggleWeightEditMode() {
            if (forceStopEditMode) return
            // Disable edit mode on Step 2 (SetExecution)
            if (calibrationStep == CalibrationStep.SetExecution) return
            isWeightInEditMode = !isWeightInEditMode
            updateInteractionTime()
            isRepsInEditMode = false

            hapticsViewModel.doGentleVibration()
        }
        Row(
            modifier = modifier
                .height(40.dp)
                .combinedClickable(
                    onClick = {
                        updateInteractionTime()
                    },
                    onLongClick = {
                        toggleWeightEditMode()
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
                )
                .semantics(mergeDescendants = true) {
                    contentDescription = "${SetValueSemantics.WeightValueDescription}: $weightText"
                    role = Role.Button
                    onClick(
                        label = "Focus weight"
                    ) {
                        updateInteractionTime()
                        true
                    }
                    onLongClick(
                        label = "Edit weight"
                    ) {
                        toggleWeightEditMode()
                        true
                    }
                },
            verticalAlignment = Alignment.CenterVertically,
        ) {
            val textColor = when {
                currentSetData.additionalWeight == previousSetData.additionalWeight -> MaterialTheme.colorScheme.onBackground
                currentSetData.additionalWeight < previousSetData.additionalWeight  -> Red
                else -> Green
            }

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
        val shouldShowWeights = currentSetData.additionalWeight == 0.0 || availableWeights.isNotEmpty()

        Column (
            modifier = customModifier,
            verticalArrangement = Arrangement.Top
        ){
            Box(
                modifier = Modifier.fillMaxWidth(),
                contentAlignment = Alignment.Center
            ) {
                Row(
                    verticalAlignment = Alignment.Top,
                    horizontalArrangement = Arrangement.spacedBy(5.dp)
                ) {
                    if(shouldShowWeights) {
                        Column(
                            modifier = Modifier.width(70.dp),
                            horizontalAlignment = Alignment.CenterHorizontally,
                            verticalArrangement = Arrangement.spacedBy(2.5.dp, Alignment.Top)
                        ) {
                            Text(
                                text = "WEIGHT (KG)",
                                style = headerStyle,
                                textAlign = TextAlign.Center,
                                color =  MaterialTheme.colorScheme.onBackground,
                            )
                            WeightRow(modifier = Modifier.fillMaxWidth(), style = itemStyle)
                        }
                    }
                    Column(
                        modifier = Modifier.width(70.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.spacedBy(2.5.dp, Alignment.Top)
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
    }

    // Handle calibration flow steps (only if equipment is present)
    if (shouldShowCalibration && calibrationStep != null) {
        when (calibrationStep) {
            CalibrationStep.LoadSelection -> {
                customComponentWrapper {
                    CalibrationLoadSelectionScreen(
                        viewModel = viewModel,
                        hapticsViewModel = hapticsViewModel,
                        state = state,
                        equipment = state.equipment,
                        onWeightSelected = { selectedWeight ->
                            // Update set data with selected weight (additionalWeight for body weight)
                            val newSetData = currentSetData.copy(additionalWeight = selectedWeight)
                            currentSetData = newSetData.copy(volume = newSetData.calculateVolume())
                            state.currentSetData = currentSetData
                            // Move directly to set execution
                            viewModel.confirmCalibrationLoad()
                        },
                        exerciseTitleComposable = exerciseTitleComposable,
                        extraInfo = extraInfo,
                        modifier = modifier,
                        previousSetData = previousSetData
                    )
                }
                return
            }
            CalibrationStep.SetExecution -> {
                // Show normal set screen - continue to normal flow below
            }
            CalibrationStep.RIRRating -> {
                customComponentWrapper {
                    CalibrationRIRScreen(
                        initialRIR = currentSetData.calibrationRIR?.toInt() ?: 2,
                        onRIRConfirmed = { rir, formBreaks ->
                            // Store RIR and apply adjustments
                            val newSetData = currentSetData.copy(calibrationRIR = rir)
                            currentSetData = newSetData
                            state.currentSetData = currentSetData
                            viewModel.applyCalibrationRIR(rir, formBreaks)
                        },
                        hapticsViewModel = hapticsViewModel,
                        modifier = modifier
                    )
                }
                return
            }
        }
    }

    customComponentWrapper {
        Box(
            modifier = modifier.semantics {
                contentDescription = SetValueSemantics.BodyWeightSetTypeDescription
            }
        ) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .alpha(if (isInEditMode) 0f else 1f),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center
            ) {
                Column(
                    verticalArrangement = Arrangement.spacedBy(5.dp, Alignment.Bottom)
                ) {
                    exerciseTitleComposable()
                    if (extraInfo != null) {
                        //HorizontalDivider(modifier = Modifier.fillMaxWidth(), thickness = 1.dp)
                        extraInfo(state)
                    }
                    if (shouldShowCalibration && calibrationStep != null) {
                        val stepText = when (calibrationStep) {
                            CalibrationStep.LoadSelection -> "Step 1/3: Select Load"
                            CalibrationStep.SetExecution -> "Step 2/3: Complete Set"
                            CalibrationStep.RIRRating -> "Step 3/3: Rate RIR"
                        }
                        Text(
                            text = stepText,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.primary,
                            textAlign = TextAlign.Center,
                            modifier = Modifier.fillMaxWidth()
                        )
                    }
                    if (isPlateauDetected) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable {
                                    showPlateauDialog = true
                                    hapticsViewModel.doGentleVibration()
                                },
                            horizontalArrangement = Arrangement.Center,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Icon(
                                imageVector = Icons.Filled.Warning,
                                contentDescription = "Warning",
                                tint = if (showRed) Red else MaterialTheme.colorScheme.surfaceContainerHigh,
                                modifier = Modifier.size(16.dp)
                            )
                            Spacer(modifier = Modifier.width(4.dp))
                            Text(
                                text = "Plateau Detected",
                                style = MaterialTheme.typography.bodySmall.copy(
                                    fontWeight = FontWeight.Bold
                                ),
                                color = MaterialTheme.colorScheme.onBackground,
                                textAlign = TextAlign.Center
                            )
                            Spacer(modifier = Modifier.width(5.dp))
                            Icon(
                                imageVector = Icons.Filled.Info,
                                contentDescription = "Info",
                                tint = MaterialTheme.colorScheme.onBackground,
                                modifier = Modifier.size(16.dp)
                            )
                        }
                    }
                }
                Spacer(modifier = Modifier.height(10.dp))
                SetScreen(
                    customModifier = Modifier
                )
            }

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
                    onCloseClick = {
                        isRepsInEditMode = false
                        isWeightInEditMode = false
                    },
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
            }
        }
    }

    PlateauInfoDialog(
        show = showPlateauDialog,
        reason = plateauReason ?: "",
        onDismiss = { showPlateauDialog = false },
        hapticsViewModel = hapticsViewModel,
        onVisibilityChange = { isVisible ->
            if (isVisible) {
                viewModel.setDimming(false)
            } else {
                viewModel.reEvaluateDimmingForCurrentState()
            }
        }
    )
}
