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
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData

@Composable
fun WeightSetDataViewerMinimal(weightSetData: WeightSetData, style: TextStyle = MaterialTheme.typography.body1, color: Color = Color.Unspecified){
    val weightText = if (weightSetData.actualWeight % 1 == 0f) {
        "${weightSetData.actualWeight.toInt()}"
    } else {
        "${weightSetData.actualWeight}"
    }

    val repLabel = if (weightSetData.actualReps == 1) "rep" else "reps"

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
        Spacer(modifier = Modifier.width(5.dp))
        Text(
            text = "${weightSetData.actualReps}",
            style = style,
            color = color,
            textAlign = TextAlign.End
        )
        Spacer(modifier = Modifier.width(5.dp))
        Text(
            text = repLabel,
            style = style.copy(fontSize = style.fontSize * 0.625f),
            textAlign = TextAlign.Start
        )
    }
}