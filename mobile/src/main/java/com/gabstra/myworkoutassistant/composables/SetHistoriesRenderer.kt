package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.formatSecondsToMinutesSeconds
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.LightGray

@Composable
fun SetHistoriesRenderer(modifier: Modifier = Modifier, setHistories: List<SetHistory>) {
    Column(
        modifier = modifier.padding(10.dp),
        horizontalAlignment = Alignment.End,
        verticalArrangement = Arrangement.spacedBy(5.dp),
    ) {
        var index = 0
        setHistories.forEach() { set ->
            val setData = set.setData
            if(setData !is RestSetData){
                index += 1
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Text(
                        text = "${index})",
                        style = MaterialTheme.typography.bodyMedium,
                        color = LightGray
                    )
                    when (setData) {
                        is WeightSetData -> {
                            val repLabel = if(setData.actualReps == 1) "rep" else "reps"

                            val weightText = if (setData.actualWeight % 1 == 0.0) {
                                "${setData.actualWeight.toInt()}"
                            } else {
                                "${setData.actualWeight}"
                            }

                            Text(
                                text = "${weightText} kg x ${setData.actualReps} ${repLabel}",
                                style = MaterialTheme.typography.bodyMedium,
                                color = LightGray
                            )
                        }

                        is BodyWeightSetData -> {
                            val repLabel = if(setData.actualReps == 1) "rep" else "reps"
                            val weightText = if (setData.additionalWeight % 1 == 0.0) {
                                "${setData.additionalWeight.toInt()}"
                            } else {
                                "${setData.additionalWeight}"
                            }

                            val text = if(setData.additionalWeight != 0.0) "${weightText} kg x ${setData.actualReps} ${repLabel}" else "${setData.actualReps} ${repLabel}"
                            Text(
                                text = text,
                                style = MaterialTheme.typography.bodyMedium,
                                color = LightGray
                            )
                        }

                        is TimedDurationSetData -> {
                            if(setData.endTimer == 0) {
                                Text(
                                    "For: ${formatSecondsToMinutesSeconds(setData.startTimer / 1000)}",
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = LightGray,
                                )
                            }else{
                                Text(
                                    "From: ${formatTime(setData.startTimer / 1000)} to ${formatTime(setData.endTimer / 1000)}",
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = LightGray,
                                )
                            }
                        }

                        is EnduranceSetData -> {
                            if(setData.endTimer == 0) {
                                Text(
                                    "For: ${formatSecondsToMinutesSeconds(setData.startTimer / 1000)}",
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = LightGray,
                                )
                            }else{
                                Text(
                                    "From: ${formatTime(setData.startTimer / 1000)} to ${formatTime(setData.endTimer / 1000)}",
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = LightGray,
                                )
                            }
                        }
                        else -> throw IllegalArgumentException("Unknown set type")
                    }
                }
            }else{
                // Temporarily hide rest sets from history page
                /*Row(
                    modifier = Modifier.fillMaxWidth().padding(vertical = 5.dp),
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = Alignment.CenterVertically
                ){
                    if(setData.endTimer == 0) {
                        Text(
                            "Rest for: ${formatSecondsToMinutesSeconds(setData.startTimer)}",
                            style = MaterialTheme.typography.bodyMedium,
                            color = VeryLightGray,
                        )
                    }else{
                        Text(
                            "Rest from: ${formatTime(setData.startTimer / 1000)} to ${formatTime(setData.endTimer / 1000)}",
                            style = MaterialTheme.typography.bodyMedium,
                            color = VeryLightGray,
                        )
                    }
                }*/
            }
        }
    }
}