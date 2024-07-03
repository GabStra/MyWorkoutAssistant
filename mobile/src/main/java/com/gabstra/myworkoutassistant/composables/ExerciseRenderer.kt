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
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.formatSecondsToMinutesSeconds
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
@Composable
fun ExerciseRenderer(exercise: Exercise){
    Column(modifier = Modifier
        .fillMaxWidth()
        .padding(start= 10.dp,end = 10.dp, top = 5.dp, bottom = 5.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        for (set in exercise.sets) {
            Row(
                modifier = Modifier
                    .fillMaxWidth(),
                horizontalArrangement = Arrangement.Center,
            ) {
                when (set) {
                    is WeightSet -> {
                        Text(
                            text = "x${set.reps} - ${set.weight} kg"
                        )
                    }

                    is BodyWeightSet -> {
                        Text(
                            text = "x${set.reps}"
                        )
                    }

                    is TimedDurationSet -> {
                        Text(formatSecondsToMinutesSeconds(set.timeInMillis / 1000) + " (mm:ss)")
                    }

                    is EnduranceSet -> {
                        Text(formatSecondsToMinutesSeconds(set.timeInMillis / 1000) + " (mm:ss)")
                    }
                }
            }
            if (set !== exercise.sets.last()) Divider(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = 10.dp), thickness = 1.dp, color = Color.White
            )

        }
    }
}