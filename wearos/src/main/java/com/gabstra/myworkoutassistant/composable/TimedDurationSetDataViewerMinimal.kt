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
import com.gabstra.myworkoutassistant.data.FormatTime
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData

@Composable
fun TimedDurationSetDataViewerMinimal(timedDurationSetData: TimedDurationSetData){
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.Center
    ) {
        Text(
            text =  FormatTime(timedDurationSetData.startTimer / 1000),
            style = MaterialTheme.typography.body1
        )
    }
}