package com.gabstra.myworkoutassistant.composables

import android.util.Log
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.formatSecondsToMinutesSeconds
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.shared.DisabledContentGray
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData

@Composable
fun SetHistoriesRenderer(
    modifier: Modifier = Modifier,
    setHistories: List<SetHistory>,
    appViewModel: AppViewModel,
    workout: Workout
) {
    Column(
        modifier = modifier.padding(5.dp),
        verticalArrangement = Arrangement.spacedBy(5.dp),
    ) {
        var index = 0

        val exerciseId = setHistories[0].exerciseId!!
        var exercise = appViewModel.getExerciseById(workout,exerciseId)
        val equipment = if(exercise!!.equipmentId != null) appViewModel.getEquipmentById(exercise.equipmentId!!) else null

        if(equipment != null){
            Text(
                modifier = Modifier.fillMaxWidth(),
                textAlign = TextAlign.Center,
                text = "Equipment: ${equipment.name}", style = MaterialTheme.typography.bodyMedium
            )
        }

        Row {
            Text(
                modifier = Modifier.weight(1f),
                text = "#",
                style = MaterialTheme.typography.titleSmall,
                textAlign = TextAlign.Center,
                color = MaterialTheme.colorScheme.onBackground,
            )
            if(exercise.exerciseType == ExerciseType.BODY_WEIGHT || exercise.exerciseType == ExerciseType.WEIGHT){
                Text(
                    modifier = Modifier.weight(1f),
                    text = "WEIGHT (KG)",
                    style = MaterialTheme.typography.titleSmall,
                    textAlign = TextAlign.Center,
                    color = MaterialTheme.colorScheme.onBackground,
                )
                Text(
                    modifier = Modifier.weight(1f),
                    text = "REPS",
                    style = MaterialTheme.typography.titleSmall,
                    textAlign = TextAlign.Center,
                    color = MaterialTheme.colorScheme.onBackground,
                )
            }else{
                Text(
                    modifier = Modifier.weight(1f),
                    text = "TIME",
                    textAlign = TextAlign.Center,
                    style = MaterialTheme.typography.titleSmall,
                    color = MaterialTheme.colorScheme.onBackground,
                )
            }
        }

        setHistories.forEach() { set ->
            val setData = set.setData
            if(setData !is RestSetData){
                index += 1
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Text(
                        modifier = Modifier.weight(1f),
                        text = "$index",
                        style = MaterialTheme.typography.bodyMedium,
                        textAlign = TextAlign.Center,

                    )
                    when (setData) {
                        is WeightSetData -> {
                            val weightText = equipment!!.formatWeight(setData.actualWeight)

                            Text(
                                modifier = Modifier.weight(1f),
                                text = weightText,
                                textAlign = TextAlign.Center,
                                style = MaterialTheme.typography.bodyMedium,
                            )
                            Text(
                                modifier = Modifier.weight(1f),
                                text = "${setData.actualReps}",
                                textAlign = TextAlign.Center,
                                style = MaterialTheme.typography.bodyMedium,
                            )
                        }

                        is BodyWeightSetData -> {
                            val weightText = when{
                                setData.additionalWeight > 0 -> {

                                    equipment!!.formatWeight(setData.additionalWeight)
                                }
                                else -> "-"
                            }

                            Text(
                                modifier = Modifier.weight(1f),
                                text = weightText,
                                textAlign = TextAlign.Center,
                                style = MaterialTheme.typography.bodyMedium,
                            )
                            Text(
                                modifier = Modifier.weight(1f),
                                text = "${setData.actualReps}",
                                textAlign = TextAlign.Center,
                                style = MaterialTheme.typography.bodyMedium,
                                color = if (exercise.enabled) MaterialTheme.colorScheme.onBackground else DisabledContentGray,
                            )
                        }

                        is TimedDurationSetData -> {
                            if(setData.endTimer == 0) {
                                Text(
                                    modifier = Modifier.weight(1f),
                                    text = "For: ${formatSecondsToMinutesSeconds(setData.startTimer / 1000)}",
                                    style = MaterialTheme.typography.bodyMedium,
                                    textAlign = TextAlign.Center,
                                    color = MaterialTheme.colorScheme.onBackground,
                                )
                            }else{
                                Text(
                                    modifier = Modifier.weight(1f),
                                    text = "From: ${formatTime(setData.startTimer / 1000)} to ${formatTime(setData.endTimer / 1000)}",
                                    style = MaterialTheme.typography.bodyMedium,
                                    textAlign = TextAlign.Center,
                                    color = MaterialTheme.colorScheme.onBackground,
                                )
                            }
                        }

                        is EnduranceSetData -> {
                            if(setData.endTimer == 0) {
                                Text(
                                    modifier = Modifier.weight(1f),
                                    text = "For: ${formatSecondsToMinutesSeconds(setData.startTimer / 1000)}",
                                    style = MaterialTheme.typography.bodyMedium,
                                    textAlign = TextAlign.Center,
                                    color = MaterialTheme.colorScheme.onBackground,
                                )
                            }else{
                                Text(
                                    modifier = Modifier.weight(1f),
                                    text = "From: ${formatTime(setData.startTimer / 1000)} to ${formatTime(setData.endTimer / 1000)}",
                                    style = MaterialTheme.typography.bodyMedium,
                                    textAlign = TextAlign.Center,
                                    color = MaterialTheme.colorScheme.onBackground,
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
                            color = VeryMaterialTheme.colorScheme.onBackground,
                        )
                    }else{
                        Text(
                            "Rest from: ${formatTime(setData.startTimer / 1000)} to ${formatTime(setData.endTimer / 1000)}",
                            style = MaterialTheme.typography.bodyMedium,
                            color = VeryMaterialTheme.colorScheme.onBackground,
                        )
                    }
                }*/
            }
        }
    }
}
