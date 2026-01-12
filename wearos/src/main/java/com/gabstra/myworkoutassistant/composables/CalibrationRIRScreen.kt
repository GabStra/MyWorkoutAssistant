package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
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
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.data.HapticsViewModel

@Composable
fun CalibrationRIRScreen(
    initialRIR: Int = 2,
    onRIRConfirmed: (Double, Boolean) -> Unit,
    hapticsViewModel: HapticsViewModel,
    modifier: Modifier = Modifier
) {
    var rirValue by remember { mutableIntStateOf(initialRIR) }
    
    val headerStyle = MaterialTheme.typography.bodyExtraSmall
    val typography = MaterialTheme.typography
    val itemStyle = remember(typography) { 
        typography.numeralSmall.copy(fontWeight = FontWeight.Medium) 
    }
    
    fun onMinusClick() {
        if (rirValue > 0) {
            rirValue--
            hapticsViewModel.doGentleVibration()
        }
    }
    
    fun onPlusClick() {
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
        onRIRConfirmed(rirValue.toDouble(), formBreaks)
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
                text = "RIR",
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
                val rirText = if (rirValue == 0) {
                    "0 (Form Breaks)"
                } else if (rirValue >= 5) {
                    "$rirValue+"
                } else {
                    rirValue.toString()
                }
                
                ScalableText(
                    modifier = Modifier.fillMaxWidth(),
                    text = rirText,
                    style = itemStyle,
                    color = MaterialTheme.colorScheme.onBackground,
                    textAlign = TextAlign.Center
                )
            }
        }
    }
}
