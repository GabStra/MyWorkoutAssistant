package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
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

    Text(
        modifier = modifier
            .basicMarquee(iterations = Int.MAX_VALUE),
        text = exercise.name,
        style = MaterialTheme.typography.bodyMedium,
        color = Color.White.copy(alpha = if (exercise.enabled) .87f else .3f),
    )
    Spacer(modifier = Modifier.width(10.dp))

    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.End,
        verticalArrangement = Arrangement.spacedBy(5.dp),
    ) {
        for (component in sets) {
            Row{
                when (component) {
                    is WeightSet -> {
                        Text(
                            text = "x${component.reps} @ ${component.weight} kg",
                            style = MaterialTheme.typography.bodyMedium,
                            color = Color.White.copy(alpha = if (exercise.enabled) .87f else .3f),
                        )
                    }

                    is BodyWeightSet -> {
                        Text(
                            text = "x${component.reps}",
                            style = MaterialTheme.typography.bodyMedium,
                            color = Color.White.copy(alpha = if (exercise.enabled) .87f else .3f),
                        )
                    }

                    is TimedDurationSet -> {
                        Text(
                            text= formatTime(component.timeInMillis / 1000),
                            style = MaterialTheme.typography.bodyMedium,
                            color = Color.White.copy(alpha = if (exercise.enabled) .87f else .3f),
                        )
                    }

                    is EnduranceSet -> {
                        Text(
                            formatTime(component.timeInMillis / 1000),
                            style = MaterialTheme.typography.bodyMedium,
                            color = Color.White.copy(alpha = if (exercise.enabled) .87f else .3f),
                        )
                    }
                    is RestSet -> {
                        Text(
                            "Rest for: "+formatTime(component.timeInSeconds),
                            style = MaterialTheme.typography.bodyMedium,
                            color = Color.White.copy(alpha = if (exercise.enabled) .87f else .3f),
                        )
                    }
                }
            }
        }
    }
}