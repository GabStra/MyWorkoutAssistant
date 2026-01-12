package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun CalibrationLoadConfirmationScreen(
    selectedWeight: Double,
    equipment: WeightLoadedEquipment?,
    isBodyWeight: Boolean,
    onConfirm: () -> Unit,
    onChange: () -> Unit,
    hapticsViewModel: HapticsViewModel,
    modifier: Modifier = Modifier
) {
    val headerStyle = MaterialTheme.typography.bodyExtraSmall
    val typography = MaterialTheme.typography
    val itemStyle = remember(typography) { 
        typography.numeralSmall.copy(fontWeight = FontWeight.Medium) 
    }
    
    val weightText = if (equipment != null) {
        if (isBodyWeight && selectedWeight == 0.0) {
            "BW"
        } else {
            equipment.formatWeight(selectedWeight)
        }
    } else {
        selectedWeight.toString()
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
                text = "CONFIRM LOAD",
                style = headerStyle,
                textAlign = TextAlign.Center,
                color = MaterialTheme.colorScheme.onBackground,
                modifier = Modifier.padding(bottom = 10.dp)
            )
            
            ScalableText(
                modifier = Modifier.fillMaxWidth(),
                text = weightText,
                style = itemStyle,
                color = MaterialTheme.colorScheme.onBackground,
                textAlign = TextAlign.Center
            )
            
            Text(
                text = "Tap to confirm",
                style = MaterialTheme.typography.bodySmall,
                textAlign = TextAlign.Center,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 20.dp)
                    .clickable {
                        hapticsViewModel.doGentleVibration()
                        onConfirm()
                    }
            )
            
            Text(
                text = "Long press to change",
                style = MaterialTheme.typography.bodySmall,
                textAlign = TextAlign.Center,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 10.dp)
                    .combinedClickable(
                        onClick = {},
                        onLongClick = {
                            hapticsViewModel.doGentleVibration()
                            onChange()
                        }
                    )
            )
        }
    }
}
