package com.gabstra.myworkoutassistant.composable

import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowRight
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.VibrateOnce
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData

@Composable
fun WeightSetDataViewer(weightSetData: WeightSetData){
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
                text = "${weightSetData.actualReps}",
                style = MaterialTheme.typography.display3
            )
            Spacer(modifier = Modifier.width(5.dp))
            Text(
                text = "reps",
                style = MaterialTheme.typography.body1,
                modifier = Modifier
                    .width(35.dp)
                    .padding(0.dp, 0.dp, 0.dp, 4.dp)
            )
        }
    }
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
                text = "${weightSetData.actualWeight}",
                style = MaterialTheme.typography.display3
            )
            Spacer(modifier = Modifier.width(5.dp))
            Text(
                text = "kg",
                style = MaterialTheme.typography.body1,
                modifier = Modifier
                    .width(35.dp)
                    .padding(0.dp, 0.dp, 0.dp, 4.dp)
            )
        }
    }
}