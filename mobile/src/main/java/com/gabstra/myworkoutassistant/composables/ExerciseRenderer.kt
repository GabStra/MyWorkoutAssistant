package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Divider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.formatSecondsToMinutesSeconds
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
@Composable
fun ExerciseRenderer(exercise: Exercise, modifier: Modifier = Modifier){
    Column(modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        for (set in exercise.sets) {
            Row(
                modifier = Modifier
                    .fillMaxWidth(),
                horizontalArrangement = Arrangement.Center
            ) {
                when (set) {
                    is WeightSet -> {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth(),
                        ){
                            Text(
                                text = "x${set.reps}",
                                textAlign = TextAlign.End,
                                style = MaterialTheme.typography.bodySmall,
                            )
                            Spacer(modifier = Modifier.width(5.dp))
                            Text(
                                text = "@",
                                style = MaterialTheme.typography.bodySmall,
                            )
                            Spacer(modifier = Modifier.width(5.dp))
                            Text(
                                text = "${set.weight} kg",
                                style = MaterialTheme.typography.bodySmall,
                            )
                        }
                    }

                    is BodyWeightSet -> {
                        Text(
                            text = "x${set.reps}",
                            textAlign = TextAlign.Center,
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }

                    is TimedDurationSet -> {
                        Text(
                            text=formatSecondsToMinutesSeconds(set.timeInMillis / 1000) + " (mm:ss)",
                            textAlign = TextAlign.Center,
                            style = MaterialTheme.typography.bodySmall
                        )
                    }

                    is EnduranceSet -> {
                        Text(
                            formatSecondsToMinutesSeconds(set.timeInMillis / 1000) + " (mm:ss)",
                            textAlign = TextAlign.Center,
                            style = MaterialTheme.typography.bodySmall
                        )
                    }
                }
            }
        }
    }
}