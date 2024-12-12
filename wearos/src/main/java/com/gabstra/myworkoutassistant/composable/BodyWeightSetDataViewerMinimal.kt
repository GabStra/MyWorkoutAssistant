package com.gabstra.myworkoutassistant.composable

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Equipment
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData

@Composable
fun BodyWeightSetDataViewerMinimal(bodyWeightSetData: BodyWeightSetData, equipment: Equipment?, style: TextStyle = MaterialTheme.typography.body1, color: Color = Color.Unspecified){
    if(bodyWeightSetData.additionalWeight != 0.0){
        val equipmentVolumeMultiplier = equipment?.volumeMultiplier ?: 1.0

        var weight = if(equipment != null && equipment is Barbell){
            (bodyWeightSetData.additionalWeight - equipment.barWeight) / equipmentVolumeMultiplier
        }else{
            bodyWeightSetData.additionalWeight / equipmentVolumeMultiplier
        }

        val weightText = if (weight % 1 == 0.0) {
            "${weight.toInt()}"
        } else {
            "$weight"
        }

        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.Center){
            Row(verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.Center){
                Text(
                    text = weightText,
                    style = style,
                    color = color,
                    textAlign = TextAlign.End
                )
                Spacer(modifier = Modifier.width(5.dp))
                Text(
                    text = "kg",
                    style = style.copy(fontSize = style.fontSize * 0.625f),
                    textAlign = TextAlign.Start
                )
            }
            Spacer(modifier = Modifier.width(5.dp))
            Text(
                text = "x",
                style = style.copy(fontSize = style.fontSize * 0.625f),
                textAlign = TextAlign.Center
            )
            Spacer(modifier = Modifier.width(5.dp))
            Row(verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.Center){
                Text(
                    text = "${bodyWeightSetData.actualReps}",
                    style = style,
                    color = color,
                    textAlign = TextAlign.End
                )
            }
        }
    }else{
        val label = if (bodyWeightSetData.actualReps == 1) "rep" else "reps"
        Row(verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.Center){
            Text(
                text = "${bodyWeightSetData.actualReps}",
                style = style,
                color = color,
                textAlign = TextAlign.End
            )
            Spacer(modifier = Modifier.width(5.dp))
            Text(
                text = label,
                style = style.copy(fontSize = style.fontSize * 0.625f),
                textAlign = TextAlign.Start
            )
        }
    }
}