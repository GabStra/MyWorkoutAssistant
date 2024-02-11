package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Divider
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.formatSecondsToMinutesSeconds
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData

@Composable
fun SetHistoriesRenderer(setHistories: List<SetHistory>){
    Column(modifier = Modifier
        .fillMaxWidth()
        .padding(8.dp),
        horizontalAlignment = Alignment.CenterHorizontally) {
        for (set in setHistories){
            val setData = set.setData
            when(setData){
                is WeightSetData -> {
                    Text(
                        text = "x ${setData.actualReps}"
                    )
                    Spacer(modifier= Modifier.height(5.dp))
                    Text(
                        text = "${setData.actualWeight} kg"
                    )
                }
                is BodyWeightSetData -> {
                    Text(
                        text = "x ${setData.actualReps}"
                    )
                }
                is TimedDurationSetData -> {
                    Text("Timer set to: "+formatSecondsToMinutesSeconds(setData.startTimer/1000) + " (mm:ss)")
                    Spacer(modifier= Modifier.height(5.dp))
                    Text("Stopped at: "+formatSecondsToMinutesSeconds(setData.endTimer/1000) + " (mm:ss)")
                }
                is EnduranceSetData -> {
                    Text("Timer set to: "+formatSecondsToMinutesSeconds(setData.startTimer/1000) + " (mm:ss)")
                    Spacer(modifier= Modifier.height(5.dp))
                    Text("Done: "+formatSecondsToMinutesSeconds(setData.endTimer/1000) + " (mm:ss)")
                }
            }

            if(set !== setHistories.last()) Divider( modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 10.dp),thickness = 1.dp, color = Color.White)

        }
    }
}