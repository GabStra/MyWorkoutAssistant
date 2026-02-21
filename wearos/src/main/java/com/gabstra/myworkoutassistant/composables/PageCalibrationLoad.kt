package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.MediumLighterGray
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun PageCalibrationLoad(
    modifier: Modifier = Modifier,
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    state: WorkoutState.CalibrationLoadSelection,
    onWeightSelected: (Double) -> Unit,
    exerciseTitleComposable: @Composable () -> Unit,
    extraInfo: (@Composable (WorkoutState.CalibrationLoadSelection) -> Unit)? = null,
) {
    val context = LocalContext.current
    val currentSetData = state.currentSetData
    val isWeightSet = currentSetData is WeightSetData
    val isBodyWeightSet = currentSetData is BodyWeightSetData
    val equipment = state.equipment
    
    var availableWeights by remember(equipment) { mutableStateOf<Set<Double>>(emptySet()) }
    var selectedWeightIndex by remember(state.calibrationSet.id) { mutableIntStateOf(0) }
    var showPicker by remember { mutableStateOf(false) }
    var showConfirmDialog by remember { mutableStateOf(false) }
    var lastInteractionTime by remember { mutableLongStateOf(System.currentTimeMillis()) }
    
    LaunchedEffect(equipment) {
        availableWeights = if (equipment != null) {
            if (isBodyWeightSet) {
                // For body weight, include 0.0 (body weight only)
                (viewModel.getWeightByEquipment(equipment) + setOf(0.0)).sorted().toSet()
            } else {
                viewModel.getWeightByEquipment(equipment)
            }
        } else {
            emptySet()
        }
    }
    
    val initialWeight = remember(state.calibrationSet.id) {
        when {
            isWeightSet -> currentSetData.actualWeight
            isBodyWeightSet -> currentSetData.additionalWeight
            else -> 0.0
        }
    }
    
    LaunchedEffect(availableWeights, initialWeight) {
        withContext(Dispatchers.Default) {
            if (availableWeights.isEmpty()) return@withContext
            val sortedWeights = availableWeights.sorted()
            val closestIndex = sortedWeights.indexOfFirst { it >= initialWeight }
            selectedWeightIndex = if (closestIndex >= 0) closestIndex else sortedWeights.size - 1
        }
    }
    
    val sortedWeights = availableWeights.sorted()
    val selectedWeight = sortedWeights.getOrNull(selectedWeightIndex) ?: 0.0

    val typography = MaterialTheme.typography
    val headerStyle = MaterialTheme.typography.bodyExtraSmall
    val itemStyle = remember(typography) { 
        typography.numeralSmall.copy(fontWeight = FontWeight.Medium) 
    }
    
    val weightText = if (equipment != null) {
        if (isBodyWeightSet && selectedWeight == 0.0) {
            "BW"
        } else {
            equipment.formatWeight(selectedWeight)
        }
    } else {
        selectedWeight.toString()
    }
    
    val reps = remember(state.calibrationSet) {
        when (val set = state.calibrationSet) {
            is WeightSet -> set.reps
            is BodyWeightSet -> set.reps
            else -> 0
        }
    }
    
    fun updateInteractionTime() {
        lastInteractionTime = System.currentTimeMillis()
    }
    
    fun onMinusClick() {
        updateInteractionTime()
        if (selectedWeightIndex > 0) {
            selectedWeightIndex--
            hapticsViewModel.doGentleVibration()
        }
    }
    
    fun onPlusClick() {
        updateInteractionTime()
        if (selectedWeightIndex < sortedWeights.size - 1) {
            selectedWeightIndex++
            hapticsViewModel.doGentleVibration()
        }
    }
    
    fun onConfirmClick() {
        onWeightSelected(selectedWeight)
        hapticsViewModel.doGentleVibration()
    }
    
    fun onOpenPicker() {
        showPicker = true
        updateInteractionTime()
        hapticsViewModel.doGentleVibration()
    }
    
    fun onClosePicker() {
        showPicker = false
        updateInteractionTime()
    }
    
    @Composable
    fun WeightRow(modifier: Modifier = Modifier, style: TextStyle) {
        Row(
            modifier = modifier
                .height(40.dp)
                .combinedClickable(
                    onClick = {
                        updateInteractionTime()
                    },
                    onLongClick = { onOpenPicker() }
                ),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            ScalableText(
                modifier = Modifier.fillMaxWidth(),
                text = weightText,
                style = style,
                color = MaterialTheme.colorScheme.onBackground,
                textAlign = TextAlign.Center
            )
        }
    }

    // Auto-close picker after 5 seconds of inactivity
    LaunchedEffect(showPicker) {
        if (showPicker) {
            while (showPicker) {
                delay(1000) // Check every second
                if (System.currentTimeMillis() - lastInteractionTime > 5000) {
                    showPicker = false
                }
            }
        }
    }
    
    // Back button handler: single press opens dialog, closes picker if open
    CustomBackHandler(
        enabled = true,
        onPress = {
            hapticsViewModel.doGentleVibration()
        },
        onSinglePress = {
            if (showPicker) {
                onClosePicker()
            } else {
                showConfirmDialog = true
            }
        },
        onDoublePress = {
            // Double-press no longer used for confirmation
        }
    )

    Box(
        modifier = modifier.fillMaxSize(),
        contentAlignment = Alignment.TopCenter
    ) {
        if (showPicker) {
            // Picker state: only show ControlButtonsVertical
            ControlButtonsVertical(
                modifier = Modifier.fillMaxSize(),
                onMinusTap = { onMinusClick() },
                onMinusLongPress = { onMinusClick() },
                onPlusTap = { onPlusClick() },
                onPlusLongPress = { onPlusClick() },
                onCloseClick = { onClosePicker() }
            ) {
                ScalableText(
                    modifier = Modifier
                        .fillMaxWidth()
                        .combinedClickable(
                            onClick = {
                                updateInteractionTime()
                            },
                            onLongClick = {
                                onClosePicker()
                            },
                            onDoubleClick = {
                            }
                        ),
                    text = weightText,
                    style = itemStyle,
                    color = MaterialTheme.colorScheme.onBackground,
                    textAlign = TextAlign.Center
                )
            }
        } else {
            // Initial state: show exercise info, header, and two-column layout (weight + reps)
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 10.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(5.dp, Alignment.Top)
            ) {
                exerciseTitleComposable()

                if (extraInfo != null) {
                    extraInfo(state)
                }

                // Two-column layout matching WeightSetScreen/BodyWeightSetScreen
                Box(
                    modifier = Modifier.fillMaxWidth(),
                    contentAlignment = Alignment.Center
                ) {
                    Column(
                        modifier = Modifier.width(70.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.spacedBy(2.5.dp, Alignment.Top)
                    ) {
                        Text(
                            text = "WEIGHT (KG)",
                            style = headerStyle,
                            textAlign = TextAlign.Center,
                            color = MaterialTheme.colorScheme.onBackground,
                        )
                        WeightRow(modifier = Modifier.fillMaxWidth(), style = itemStyle)
                    }
                }

                Text(
                    text = "Select load for $reps reps at 1-2 RIR",
                    style = MaterialTheme.typography.bodySmall.copy(fontWeight = FontWeight.Normal),
                    color = MediumLighterGray,
                    textAlign = TextAlign.Center,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 4.dp)
                )
            }
        }
    }

    // Trigger plate recalculation when weight changes
    LaunchedEffect(selectedWeight, currentSetData) {
        val totalWeight = when (currentSetData) {
            is WeightSetData -> selectedWeight
            is BodyWeightSetData -> selectedWeight + currentSetData.relativeBodyWeightInKg
            else -> selectedWeight
        }
        viewModel.schedulePlateRecalculation(totalWeight)
    }

    CustomDialogYesOnLongPress(
        show = showConfirmDialog,
        title = "Confirm Load",
        message = "Do you want to proceed with this load?",
        handleYesClick = {
            hapticsViewModel.doGentleVibration()
            onConfirmClick()
            showConfirmDialog = false
        },
        handleNoClick = {
            hapticsViewModel.doGentleVibration()
            showConfirmDialog = false
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            showConfirmDialog = false
        },
        onVisibilityChange = { isVisible ->
            // Dialog visibility change handling if needed
        }
    )
}
