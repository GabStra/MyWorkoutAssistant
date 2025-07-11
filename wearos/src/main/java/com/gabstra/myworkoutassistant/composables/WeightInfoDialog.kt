package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.shared.LightGray
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.equipments.toDisplayText
import com.gabstra.myworkoutassistant.shared.formatWeight

@Composable
fun WeightInfoDialog(
    show: Boolean,
    weight : Double,
    equipment: WeightLoadedEquipment?,
    onClick: () -> Unit = {}
){
    val typography = MaterialTheme.typography
    val headerStyle = remember(typography) { typography.body2.copy(fontSize = typography.body2.fontSize * 0.625f) }
    val itemStyle = remember(typography)  { typography.body2.copy(fontSize = typography.body2.fontSize * 1.625f,fontWeight = FontWeight.Bold) }

    val weightText = if (weight == 0.0) "-" else formatWeight(weight)

    if(show) {
        Dialog(
            onDismissRequest = {  },
            properties = DialogProperties(dismissOnBackPress = false, dismissOnClickOutside = false)
        ) {
            Box(
                modifier = Modifier
                    .background(MaterialTheme.colors.background.copy(alpha = 0.75f))
                    .fillMaxSize()
                    .padding(25.dp)
                    .clickable(
                        interactionSource = remember { MutableInteractionSource() },
                        indication = null
                    ) { onClick() },
                contentAlignment = Alignment.Center
            ) {
                Column(
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    if (equipment != null) {
                        Column(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalAlignment = Alignment.CenterHorizontally,
                            verticalArrangement = Arrangement.spacedBy(2.5.dp)
                        ) {
                            Text(
                                text = "EQUIPMENT",
                                style = headerStyle,
                                textAlign = TextAlign.Center
                            )
                            ScalableText(
                                modifier = Modifier.fillMaxWidth(),
                                text = equipment.type.toDisplayText(),
                                style = itemStyle,
                                color =  LightGray,
                                textAlign = TextAlign.Center
                            )
                        }
                        Column(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalAlignment = Alignment.CenterHorizontally,
                            verticalArrangement = Arrangement.spacedBy(2.5.dp)
                        ) {
                            Text(
                                text = "WEIGHT (KG)",
                                style = headerStyle,
                                textAlign = TextAlign.Center
                            )
                            ScalableText(
                                modifier = Modifier.fillMaxWidth(),
                                text =  equipment.formatWeight(weight),
                                style = itemStyle,
                                color =  LightGray,
                                textAlign = TextAlign.Center
                            )
                        }
                        Column(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalAlignment = Alignment.CenterHorizontally,
                            verticalArrangement = Arrangement.spacedBy(2.5.dp)
                        ) {
                            Text(
                                text = "TOTAL (KG)",
                                style = headerStyle,
                                textAlign = TextAlign.Center
                            )
                            ScalableText(
                                modifier = Modifier.fillMaxWidth(),
                                text = weightText,
                                style = itemStyle,
                                color =  LightGray,
                                textAlign = TextAlign.Center
                            )
                        }
                    }else{
                        Column(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalAlignment = Alignment.CenterHorizontally,
                            verticalArrangement = Arrangement.spacedBy(2.5.dp)
                        ) {
                            Text(
                                text = "EQUIPMENT",
                                style = headerStyle,
                                textAlign = TextAlign.Center
                            )
                            ScalableText(
                                modifier = Modifier.fillMaxWidth(),
                                text = "None",
                                style = itemStyle,
                                color =  LightGray,
                                textAlign = TextAlign.Center
                            )
                        }
                        Column(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalAlignment = Alignment.CenterHorizontally,
                            verticalArrangement = Arrangement.spacedBy(2.5.dp)
                        ) {
                            Text(
                                text = "WEIGHT (KG)",
                                style = headerStyle,
                                textAlign = TextAlign.Center
                            )
                            ScalableText(
                                modifier = Modifier.fillMaxWidth(),
                                text = weightText,
                                style = itemStyle,
                                color =  LightGray,
                                textAlign = TextAlign.Center
                            )
                        }
                    }
                }
            }
        }
    }
}