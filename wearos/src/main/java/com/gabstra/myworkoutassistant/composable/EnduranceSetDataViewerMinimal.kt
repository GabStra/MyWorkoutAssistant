package com.gabstra.myworkoutassistant.composable

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.FormatTime
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData


@Composable
fun EnduranceSetDataViewerMinimal(modifier: Modifier = Modifier,enduranceSetData: EnduranceSetData,style: TextStyle = MaterialTheme.typography.body1,color: Color = Color.Unspecified,historyMode : Boolean = false){
    val time = if(historyMode) enduranceSetData.endTimer else enduranceSetData.startTimer

    Text(
        modifier = modifier,
        text =  FormatTime(time / 1000),
        style = style,
        color = color
    )
}