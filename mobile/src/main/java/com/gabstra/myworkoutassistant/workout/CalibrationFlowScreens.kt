package com.gabstra.myworkoutassistant.workout

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import com.gabstra.myworkoutassistant.shared.workout.calibration.CalibrationUiLabels
import com.gabstra.myworkoutassistant.shared.workout.calibration.applyCalibrationRIR
import com.gabstra.myworkoutassistant.shared.workout.calibration.confirmCalibrationLoad
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import kotlinx.coroutines.delay
import kotlin.math.abs

@Composable
fun CalibrationLoadScreen(
    viewModel: WorkoutViewModel,
    hapticsViewModel: HapticsViewModel,
    state: WorkoutState.CalibrationLoadSelection,
) {
    val exercise = remember(state.exerciseId) { viewModel.exercisesById[state.exerciseId]!! }
    val equipment = state.equipmentId?.let { viewModel.getEquipmentById(it) }
    val currentData = state.currentSetData
    val isBodyWeightSet = currentData is BodyWeightSetData

    var availableWeights by remember(equipment) { mutableStateOf<Set<Double>>(emptySet()) }
    var selectedWeightIndex by remember(state.calibrationSet.id) { mutableIntStateOf(0) }
    var showConfirmDialog by remember { mutableStateOf(false) }
    var lastInteractionTime by remember { mutableLongStateOf(System.currentTimeMillis()) }

    LaunchedEffect(equipment) {
        availableWeights = if (equipment != null) {
            if (isBodyWeightSet) {
                (viewModel.getWeightByEquipment(equipment) + setOf(0.0)).sorted().toSet()
            } else {
                viewModel.getWeightByEquipment(equipment)
            }
        } else {
            emptySet()
        }
    }

    val initialWeight = remember(state.calibrationSet.id) {
        when (currentData) {
            is WeightSetData -> currentData.actualWeight
            is BodyWeightSetData -> currentData.additionalWeight
            else -> 0.0
        }
    }

    LaunchedEffect(availableWeights, initialWeight) {
        if (availableWeights.isEmpty()) return@LaunchedEffect
        val sorted = availableWeights.sorted()
        val closest = sorted.minByOrNull { abs(it - initialWeight) } ?: sorted.first()
        selectedWeightIndex = sorted.indexOf(closest).coerceAtLeast(0)
    }

    val sortedWeights = availableWeights.sorted()
    val selectedWeight = sortedWeights.getOrElse(selectedWeightIndex.coerceAtLeast(0)) { initialWeight }
    val reps = when (val set = state.calibrationSet) {
        is WeightSet -> set.reps
        is BodyWeightSet -> set.reps
        else -> 0
    }
    val weightText = if (equipment == null) {
        selectedWeight.toString()
    } else if (isBodyWeightSet && selectedWeight == 0.0) {
        "BW"
    } else {
        equipment.formatWeight(selectedWeight)
    }

    fun touch() {
        lastInteractionTime = System.currentTimeMillis()
    }

    fun onMinus() {
        touch()
        if (selectedWeightIndex > 0) {
            selectedWeightIndex--
            hapticsViewModel.doGentleVibration()
        }
    }

    fun onPlus() {
        touch()
        if (selectedWeightIndex < sortedWeights.size - 1) {
            selectedWeightIndex++
            hapticsViewModel.doGentleVibration()
        }
    }

    LaunchedEffect(selectedWeight, currentData) {
        val totalWeight = when (currentData) {
            is WeightSetData -> selectedWeight
            is BodyWeightSetData -> selectedWeight + currentData.relativeBodyWeightInKg
            else -> selectedWeight
        }
        viewModel.schedulePlateRecalculation(totalWeight)
    }

    LaunchedEffect(showConfirmDialog) {
        if (showConfirmDialog) {
            while (showConfirmDialog) {
                delay(1000)
                if (System.currentTimeMillis() - lastInteractionTime > 5000) {
                    showConfirmDialog = false
                }
            }
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 20.dp, vertical = 12.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(12.dp, Alignment.CenterVertically)
    ) {
        Text(
            text = exercise.name,
            style = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.SemiBold),
            textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth()
        )

        Text(
            text = "WEIGHT (KG)",
            style = MaterialTheme.typography.titleSmall,
            textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth()
        )

        ControlButtonsVertical(
            modifier = Modifier.weight(1f),
            onMinusTap = ::onMinus,
            onMinusLongPress = ::onMinus,
            onPlusTap = ::onPlus,
            onPlusLongPress = ::onPlus
        ) {
            ScalableText(
                modifier = Modifier.fillMaxWidth(),
                text = weightText,
                style = MaterialTheme.typography.displayLarge.copy(fontWeight = FontWeight.Bold),
                textAlign = TextAlign.Center
            )
        }

        Text(
            text = CalibrationUiLabels.selectLoadInstruction(reps),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth()
        )

        ButtonWithText(
            text = CalibrationUiLabels.ConfirmLoad,
            style = AppButtonStyle.Filled,
            onClick = {
                touch()
                showConfirmDialog = true
            }
        )
    }

    CustomDialogYesOnLongPress(
        show = showConfirmDialog,
        title = CalibrationUiLabels.ConfirmLoad,
        message = CalibrationUiLabels.ConfirmLoadMessage,
        handleNoClick = {
            hapticsViewModel.doGentleVibration()
            showConfirmDialog = false
        },
        handleYesClick = {
            val updated = when (val data = state.currentSetData) {
                is WeightSetData -> {
                    val newData = data.copy(actualWeight = selectedWeight)
                    newData.copy(volume = newData.calculateVolume())
                }
                is BodyWeightSetData -> {
                    val newData = data.copy(additionalWeight = selectedWeight)
                    newData.copy(volume = newData.calculateVolume())
                }
                else -> data
            }
            state.currentSetData = updated
            hapticsViewModel.doGentleVibration()
            viewModel.confirmCalibrationLoad()
            viewModel.lightScreenUp()
            showConfirmDialog = false
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = { showConfirmDialog = false },
        onVisibilityChange = { isVisible ->
            if (isVisible) viewModel.setDimming(false) else viewModel.reEvaluateDimmingForCurrentState()
        }
    )
}

@Composable
fun CalibrationRIRScreen(
    viewModel: WorkoutViewModel,
    hapticsViewModel: HapticsViewModel,
    state: WorkoutState.CalibrationRIRSelection,
) {
    val exercise = remember(state.exerciseId) { viewModel.exercisesById[state.exerciseId]!! }
    val initialRir = remember(state.currentSetData) {
        when (val setData = state.currentSetData) {
            is WeightSetData -> setData.calibrationRIR?.toInt() ?: 2
            is BodyWeightSetData -> setData.calibrationRIR?.toInt() ?: 2
            else -> 2
        }
    }

    var rirValue by remember { mutableIntStateOf(initialRir) }
    var showConfirmDialog by remember { mutableStateOf(false) }

    fun onMinus() {
        if (rirValue > 0) {
            rirValue--
            hapticsViewModel.doGentleVibration()
        }
    }

    fun onPlus() {
        if (rirValue < 10) {
            rirValue++
            hapticsViewModel.doGentleVibration()
        }
    }

    val rirText = if (rirValue >= 5) "$rirValue+" else rirValue.toString()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 20.dp, vertical = 12.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(12.dp, Alignment.CenterVertically)
    ) {
        Text(
            text = exercise.name,
            style = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.SemiBold),
            textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth()
        )

        Text(
            text = "RIR",
            style = MaterialTheme.typography.titleSmall,
            textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth()
        )

        ControlButtonsVertical(
            modifier = Modifier.weight(1f),
            onMinusTap = ::onMinus,
            onMinusLongPress = ::onMinus,
            onPlusTap = ::onPlus,
            onPlusLongPress = ::onPlus
        ) {
            ScalableText(
                modifier = Modifier.fillMaxWidth(),
                text = rirText,
                style = MaterialTheme.typography.displayLarge.copy(fontWeight = FontWeight.Bold),
                textAlign = TextAlign.Center
            )
        }

        Text(
            text = CalibrationUiLabels.FormBreaksHint,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth()
        )

        ButtonWithText(
            text = CalibrationUiLabels.ConfirmRir,
            style = AppButtonStyle.Filled,
            onClick = { showConfirmDialog = true }
        )
    }

    CustomDialogYesOnLongPress(
        show = showConfirmDialog,
        title = CalibrationUiLabels.ConfirmRir,
        message = CalibrationUiLabels.ConfirmRirMessage,
        handleNoClick = {
            hapticsViewModel.doGentleVibration()
            showConfirmDialog = false
        },
        handleYesClick = {
            val rir = rirValue.toDouble()
            val formBreaks = rirValue == 0
            state.currentSetData = when (val currentData = state.currentSetData) {
                is WeightSetData -> currentData.copy(calibrationRIR = rir)
                is BodyWeightSetData -> currentData.copy(calibrationRIR = rir)
                else -> currentData
            }
            hapticsViewModel.doGentleVibration()
            viewModel.applyCalibrationRIR(rir = rir, formBreaks = formBreaks)
            viewModel.lightScreenUp()
            showConfirmDialog = false
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = { showConfirmDialog = false },
        onVisibilityChange = { isVisible ->
            if (isVisible) viewModel.setDimming(false) else viewModel.reEvaluateDimmingForCurrentState()
        }
    )
}
