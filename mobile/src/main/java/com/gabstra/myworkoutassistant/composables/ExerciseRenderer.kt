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
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.ui.theme.LightGray
import com.gabstra.myworkoutassistant.ui.theme.MediumGray

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
                color = if (exercise.enabled) LightGray else MediumGray,
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
                    color = if (exercise.enabled) LightGray else MediumGray,
                )
            },
            content = {
                Column(
                    modifier = Modifier.padding(10.dp),
                    verticalArrangement = Arrangement.spacedBy(5.dp),
                ) {
                    var index = 0
                    sets.forEach() { set ->
                        if(set !is RestSet){
                            index += 1
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween
                            ) {
                                Text(
                                    text = "$index)",
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = if (exercise.enabled) LightGray else MediumGray,
                                )
                                when (set) {
                                    is WeightSet -> {
                                        val repLabel = if(set.reps == 1) "rep" else "reps"

                                        val weightText = if (set.weight % 1 == 0.0) {
                                            "${set.weight.toInt()}"
                                        } else {
                                            "${set.weight}"
                                        }

                                        Text(
                                            text = "${weightText} kg x ${set.reps} ${repLabel}",
                                            style = MaterialTheme.typography.bodyMedium,
                                            color = if (exercise.enabled) LightGray else MediumGray,
                                        )
                                    }

                                    is BodyWeightSet -> {
                                        val repLabel = if(set.reps == 1) "rep" else "reps"

                                        Text(
                                            text = if(set.additionalWeight<=0) "${set.reps} ${repLabel}" else "${set.additionalWeight} kg x ${set.reps} ${repLabel}",
                                            style = MaterialTheme.typography.bodyMedium,
                                            color = if (exercise.enabled) LightGray else MediumGray,
                                        )
                                    }

                                    is TimedDurationSet -> {
                                        Text(
                                            text= formatTime(set.timeInMillis / 1000),
                                            style = MaterialTheme.typography.bodyMedium,
                                            color = if (exercise.enabled) LightGray else MediumGray,
                                        )
                                    }

                                    is EnduranceSet -> {
                                        Text(
                                            formatTime(set.timeInMillis / 1000),
                                            style = MaterialTheme.typography.bodyMedium,
                                            color = if (exercise.enabled) LightGray else MediumGray,
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
                                    color = if (exercise.enabled) LightGray else MediumGray,
                                )
                            }
                        }
                    }
                }
            }
        )
    }
}