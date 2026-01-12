package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

@Composable
fun CalibrationLoadSelectionScreen(
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    state: WorkoutState.Set,
    equipment: WeightLoadedEquipment?,
    onWeightSelected: (Double) -> Unit,
    modifier: Modifier = Modifier
) {
    val currentSetData = state.currentSetData
    val isWeightSet = currentSetData is WeightSetData
    val isBodyWeightSet = currentSetData is BodyWeightSetData
    
    var availableWeights by remember(equipment) { mutableStateOf<Set<Double>>(emptySet()) }
    var selectedWeightIndex by remember(state.set.id) { mutableIntStateOf(0) }
    
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
    
    val initialWeight = remember(state.set.id) {
        when {
            isWeightSet -> (currentSetData as WeightSetData).actualWeight
            isBodyWeightSet -> (currentSetData as BodyWeightSetData).additionalWeight
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
    
    val headerStyle = MaterialTheme.typography.bodyExtraSmall
    val typography = MaterialTheme.typography
    val itemStyle = remember(typography) { 
        typography.numeralSmall.copy(fontWeight = FontWeight.Medium) 
    }
    
    fun onMinusClick() {
        if (selectedWeightIndex > 0) {
            selectedWeightIndex--
            hapticsViewModel.doGentleVibration()
        }
    }
    
    fun onPlusClick() {
        if (selectedWeightIndex < sortedWeights.size - 1) {
            selectedWeightIndex++
            hapticsViewModel.doGentleVibration()
        }
    }
    
    fun onConfirmClick() {
        onWeightSelected(selectedWeight)
        hapticsViewModel.doGentleVibration()
    }
    
    Box(
        modifier = modifier.fillMaxSize(),
        contentAlignment = Alignment.Center
    ) {
        Column(
            modifier = Modifier.fillMaxWidth(),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center
        ) {
            Text(
                text = "SELECT LOAD",
                style = headerStyle,
                textAlign = TextAlign.Center,
                color = MaterialTheme.colorScheme.onBackground
            )
            
            ControlButtonsVertical(
                modifier = Modifier.fillMaxSize(),
                onMinusTap = { onMinusClick() },
                onMinusLongPress = { onMinusClick() },
                onPlusTap = { onPlusClick() },
                onPlusLongPress = { onPlusClick() },
                onCloseClick = { onConfirmClick() }
            ) {
                val weightText = if (equipment != null) {
                    if (isBodyWeightSet && selectedWeight == 0.0) {
                        "BW"
                    } else {
                        equipment.formatWeight(selectedWeight)
                    }
                } else {
                    selectedWeight.toString()
                }
                
                ScalableText(
                    modifier = Modifier.fillMaxWidth(),
                    text = weightText,
                    style = itemStyle,
                    color = MaterialTheme.colorScheme.onBackground,
                    textAlign = TextAlign.Center
                )
            }
        }
    }
}
