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
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData


@Composable
fun BodyWeightSetDataViewer(bodyWeightSetData: BodyWeightSetData){
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.End
    ) {
        Row(
            verticalAlignment = Alignment.Bottom,
            horizontalArrangement = Arrangement.End
        ) {

            Text(
                text = "${bodyWeightSetData.actualReps}",
                style = MaterialTheme.typography.title1
            )
            Spacer(modifier = Modifier.width(5.dp))
            Text(
                text = "reps",
                style = MaterialTheme.typography.body1,
                modifier = Modifier.width(35.dp).padding(0.dp,0.dp,0.dp,1.dp)
            )
        }
    }
}