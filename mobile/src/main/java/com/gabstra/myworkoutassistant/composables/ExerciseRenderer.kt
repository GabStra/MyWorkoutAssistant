package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.formatSecondsToMinutesSeconds
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
@Composable
fun ExerciseRenderer(exercise: Exercise){
    Row (
        horizontalArrangement = Arrangement.SpaceEvenly,
        modifier = Modifier
            .fillMaxWidth()
            .padding(8.dp)
    ){
        for (set in exercise.sets){
            Column( horizontalAlignment = Alignment.End) {
                when(set){
                    is WeightSet -> {
                        Text(
                            text = "x${set.reps}"
                        )
                        Spacer(modifier= Modifier.height(5.dp))
                        Text(
                            text = "${set.weight}kg"
                        )
                    }
                    is BodyWeightSet -> {
                        Text(
                            text = "x${set.reps}"
                        )
                    }
                    is TimedDurationSet -> {
                        Text(formatSecondsToMinutesSeconds(set.timeInMillis/1000))
                    }
                    is EnduranceSet -> {
                        Text(formatSecondsToMinutesSeconds(set.timeInMillis/1000))
                    }
                }
            }
        }
    }
}