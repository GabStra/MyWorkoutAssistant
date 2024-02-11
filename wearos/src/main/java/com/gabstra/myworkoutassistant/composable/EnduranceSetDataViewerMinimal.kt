package com.gabstra.myworkoutassistant.composable

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.FormatTime
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData


@Composable
fun EnduranceSetDataViewerMinimal(enduranceSetData: EnduranceSetData){
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.Center
    ) {
        Text(
            text =  FormatTime(enduranceSetData.startTimer / 1000),
            style = MaterialTheme.typography.body1
        )
    }
}