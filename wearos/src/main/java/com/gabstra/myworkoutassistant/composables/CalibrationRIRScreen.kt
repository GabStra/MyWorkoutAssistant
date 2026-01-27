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
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.composables.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import kotlinx.coroutines.delay

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun CalibrationRIRScreen(
    modifier: Modifier = Modifier,
    state: WorkoutState.CalibrationRIRSelection,
    onRIRConfirmed: (Double, Boolean) -> Unit,
    hapticsViewModel: HapticsViewModel
) {
    val initialRIR = remember(state.currentSetData) {
        when (val setData = state.currentSetData) {
            is WeightSetData -> setData.calibrationRIR?.toInt() ?: 2
            is BodyWeightSetData -> setData.calibrationRIR?.toInt() ?: 2
            else -> 2
        }
    }
    var rirValue by remember { mutableIntStateOf(initialRIR) }
    var showPicker by remember { mutableStateOf(false) }
    var showConfirmDialog by remember { mutableStateOf(false) }
    var lastInteractionTime by remember { mutableLongStateOf(System.currentTimeMillis()) }
    
    val typography = MaterialTheme.typography
    val itemStyle = remember(typography) { 
        typography.numeralSmall.copy(fontWeight = FontWeight.Medium) 
    }
    val rirLabelStyle = MaterialTheme.typography.titleLarge.copy(
        fontWeight = FontWeight.SemiBold
    )
    
    fun updateInteractionTime() {
        lastInteractionTime = System.currentTimeMillis()
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
    
    fun onMinusClick() {
        updateInteractionTime()
        if (rirValue > 0) {
            rirValue--
            hapticsViewModel.doGentleVibration()
        }
    }
    
    fun onPlusClick() {
        updateInteractionTime()
        if (rirValue < 10) {
            rirValue++
            hapticsViewModel.doGentleVibration()
        }
    }
    
    fun onConfirmClick() {
        // RIR 0 can mean either 0 RIR or form breaks
        // For now, we'll treat RIR 0 as form breaks if user confirms at 0
        // In the future, we could add a separate "Form Breaks" option
        val formBreaks = rirValue == 0
        
        // Update set data with RIR
        val newSetData = when (val currentData = state.currentSetData) {
            is WeightSetData -> currentData.copy(calibrationRIR = rirValue.toDouble())
            is BodyWeightSetData -> currentData.copy(calibrationRIR = rirValue.toDouble())
            else -> currentData
        }
        state.currentSetData = newSetData
        
        onRIRConfirmed(rirValue.toDouble(), formBreaks)
        hapticsViewModel.doGentleVibration()
    }
    
    val rirText = if (rirValue == 0) {
        "0 (Form Breaks)"
    } else if (rirValue >= 5) {
        "$rirValue+"
    } else {
        rirValue.toString()
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
    
    val context = LocalContext.current
    
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
    
    @Composable
    fun RIRRow(modifier: Modifier = Modifier, style: TextStyle) {
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
                text = rirText,
                style = style,
                color = MaterialTheme.colorScheme.onBackground,
                textAlign = TextAlign.Center
            )
        }
    }
    
    Box(
        modifier = modifier.fillMaxSize(),
        contentAlignment = Alignment.Center
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
                    text = rirText,
                    style = itemStyle,
                    color = MaterialTheme.colorScheme.onBackground,
                    textAlign = TextAlign.Center
                )
            }
        } else {
            // Initial state: show header and RIR value
            Column(
                modifier = Modifier.fillMaxWidth(),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(5.dp, Alignment.CenterVertically)
            ) {
                Text(
                    text = "RIR",
                    style = rirLabelStyle,
                    textAlign = TextAlign.Center,
                    color = MaterialTheme.colorScheme.onBackground
                )
                
                RIRRow(modifier = Modifier.fillMaxWidth(), style = itemStyle)
            }
        }
    }

    CustomDialogYesOnLongPress(
        show = showConfirmDialog,
        title = "Confirm RIR",
        message = "Do you want to proceed with this RIR?",
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
