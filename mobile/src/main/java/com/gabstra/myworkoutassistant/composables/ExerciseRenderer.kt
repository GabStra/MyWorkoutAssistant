package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.basicMarquee
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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.LightGray
import com.gabstra.myworkoutassistant.shared.MediumLightGray
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise

@Composable
fun ExerciseRenderer(
    exercise: Exercise,
    modifier: Modifier = Modifier,
    showRest:Boolean,
    appViewModel: AppViewModel
){
    var sets = exercise.sets

    if(!showRest)
        sets = sets.filter { it !is RestSet }

    if(sets.isEmpty()){
        Row(
            modifier = Modifier.padding(15.dp),
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically
        ){
            Text(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 10.dp)
                    .basicMarquee(iterations = Int.MAX_VALUE),
                text = exercise.name,
                style = MaterialTheme.typography.bodyLarge,
                color = if (exercise.enabled) LightGray else MediumLightGray,
            )
        }
    }else{
        ExpandableContainer(
            isOpen = false,
            modifier = modifier,
            isExpandable = true,
            title = { m ->
                Text(
                    modifier = m
                        .fillMaxWidth()
                        .padding(horizontal = 10.dp)
                        .basicMarquee(iterations = Int.MAX_VALUE),
                    text = exercise.name,
                    style = MaterialTheme.typography.bodyLarge,
                    color = if (exercise.enabled) LightGray else MediumLightGray,
                )
            },
            content = {
                Column(
                    modifier = Modifier.padding(5.dp),
                    verticalArrangement = Arrangement.spacedBy(5.dp),
                ) {
                    val equipment = if(exercise.equipmentId != null) appViewModel.getEquipmentById(exercise.equipmentId!!) else null

                    if(equipment != null){
                        Text(
                            modifier = Modifier.fillMaxWidth(),
                            textAlign = TextAlign.Center,
                            text = "Equipment: ${equipment.name}", style = MaterialTheme.typography.bodyMedium
                        )
                    }

                    var index = 0
                    Row {
                        Text(
                            modifier = Modifier.weight(1f),
                            text = "#",
                            style = MaterialTheme.typography.titleSmall,
                            textAlign = TextAlign.Center,
                            color = LightGray,
                        )
                        if(exercise.exerciseType == ExerciseType.BODY_WEIGHT || exercise.exerciseType == ExerciseType.WEIGHT){
                            Text(
                                modifier = Modifier.weight(1f),
                                text = "WEIGHT (KG)",
                                style = MaterialTheme.typography.titleSmall,
                                textAlign = TextAlign.Center,
                                color = LightGray,
                            )
                            Text(
                                modifier = Modifier.weight(1f),
                                text = "REPS",
                                style = MaterialTheme.typography.titleSmall,
                                textAlign = TextAlign.Center,
                                color = LightGray,
                            )
                        }else{
                            Text(
                                modifier = Modifier.weight(1f),
                                text = "TIME",
                                textAlign = TextAlign.Center,
                                style = MaterialTheme.typography.titleSmall,
                                color = LightGray,
                            )
                        }
                    }


                    sets.forEach() { set ->
                        if(set !is RestSet){
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
                                    color = if (exercise.enabled) LightGray else MediumLightGray,
                                )
                                when (set) {
                                    is WeightSet -> {
                                        val weightText = equipment!!.formatWeight(set.weight)

                                        Text(
                                            modifier = Modifier.weight(1f),
                                            text = weightText,
                                            textAlign = TextAlign.Center,
                                            style = MaterialTheme.typography.bodyMedium,
                                            color = if (exercise.enabled) LightGray else MediumLightGray,
                                        )
                                        Text(
                                            modifier = Modifier.weight(1f),
                                            text = "${set.reps}",
                                            textAlign = TextAlign.Center,
                                            style = MaterialTheme.typography.bodyMedium,
                                            color = if (exercise.enabled) LightGray else MediumLightGray,
                                        )
                                    }

                                    is BodyWeightSet -> {
                                        val weightText = when{
                                            set.additionalWeight > 0 -> {

                                                equipment!!.formatWeight(set.additionalWeight)
                                            }
                                            else -> "-"
                                        }

                                        Text(
                                            modifier = Modifier.weight(1f),
                                            text = weightText,
                                            textAlign = TextAlign.Center,
                                            style = MaterialTheme.typography.bodyMedium,
                                            color = if (exercise.enabled) LightGray else MediumLightGray,
                                        )
                                        Text(
                                            modifier = Modifier.weight(1f),
                                            text = "${set.reps}",
                                            textAlign = TextAlign.Center,
                                            style = MaterialTheme.typography.bodyMedium,
                                            color = if (exercise.enabled) LightGray else MediumLightGray,
                                        )
                                    }

                                    is TimedDurationSet -> {
                                        Text(
                                            modifier = Modifier.weight(1f),
                                            text = formatTime(set.timeInMillis / 1000),
                                            style = MaterialTheme.typography.bodyMedium,
                                            textAlign = TextAlign.Center,
                                            color = if (exercise.enabled) LightGray else MediumLightGray,
                                        )
                                    }

                                    is EnduranceSet -> {
                                        Text(
                                            modifier = Modifier.weight(1f),
                                            text =formatTime(set.timeInMillis / 1000),
                                            style = MaterialTheme.typography.bodyMedium,
                                            textAlign = TextAlign.Center,
                                            color = if (exercise.enabled) LightGray else MediumLightGray,
                                        )
                                    }
                                    else -> throw IllegalArgumentException("Unknown set type")
                                }
                            }
                        }else{
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.Center,
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Text(
                                    "Rest "+formatTime(set.timeInSeconds),
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = if (exercise.enabled) LightGray else MediumLightGray,
                                )
                            }
                        }
                    }
                }
            }
        )
    }
}