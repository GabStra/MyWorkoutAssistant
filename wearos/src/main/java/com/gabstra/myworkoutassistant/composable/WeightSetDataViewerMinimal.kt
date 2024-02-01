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
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData

@Composable
fun WeightSetDataViewerMinimal(weightSetData: WeightSetData){
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.Center
    ) {
        Text(
            text = "x${weightSetData.actualReps}",
            style = MaterialTheme.typography.body1
        )
        Spacer(modifier = Modifier.width(5.dp))
        Text(
            text = "${weightSetData.actualWeight} kg",
            style = MaterialTheme.typography.body1,
        )
    }
}