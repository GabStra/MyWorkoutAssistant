package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest

@Composable
fun ExerciseRenderer(
    exercise: Exercise,
    modifier: Modifier = Modifier,
    showRest:Boolean
){
    var sets = exercise.sets

    if(!showRest)
        sets = sets.filter { it !is RestSet }

    ExpandableContainer(
        isOpen = true,
        modifier = modifier,
        isExpandable = sets.isNotEmpty(),
        title = { m ->
            Text(
                modifier = m.fillMaxWidth().padding(horizontal = 10.dp)
                    .basicMarquee(iterations = Int.MAX_VALUE),
                text = exercise.name,
                style = MaterialTheme.typography.bodyMedium,
                color = Color.White.copy(alpha = if (exercise.enabled) .87f else .3f),
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
                                text = "Set ${index}",
                                style = MaterialTheme.typography.bodyMedium,
                                color = Color.White.copy(alpha = if (exercise.enabled) .87f else .3f),
                            )
                            when (set) {
                                is WeightSet -> {
                                    val weightText = if (set.weight % 1 == 0f) {
                                        "${set.weight.toInt()}"
                                    } else {
                                        "${set.weight}"
                                    }

                                    Text(
                                        text = "${weightText} kg x ${set.reps}",
                                        style = MaterialTheme.typography.bodyMedium,
                                        color = Color.White.copy(alpha = if (exercise.enabled) .87f else .3f),
                                    )
                                }

                                is BodyWeightSet -> {
                                    Text(
                                        text = "${set.reps}",
                                        style = MaterialTheme.typography.bodyMedium,
                                        color = Color.White.copy(alpha = if (exercise.enabled) .87f else .3f),
                                    )
                                }

                                is TimedDurationSet -> {
                                    Text(
                                        text= formatTime(set.timeInMillis / 1000),
                                        style = MaterialTheme.typography.bodyMedium,
                                        color = Color.White.copy(alpha = if (exercise.enabled) .87f else .3f),
                                    )
                                }

                                is EnduranceSet -> {
                                    Text(
                                        formatTime(set.timeInMillis / 1000),
                                        style = MaterialTheme.typography.bodyMedium,
                                        color = Color.White.copy(alpha = if (exercise.enabled) .87f else .3f),
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
                                "Rest for: "+formatTime(set.timeInSeconds),
                                style = MaterialTheme.typography.bodyMedium,
                                color = Color.White.copy(alpha = if (exercise.enabled) .87f else .3f),
                            )
                        }
                    }
                }
            }
        }
    )
}