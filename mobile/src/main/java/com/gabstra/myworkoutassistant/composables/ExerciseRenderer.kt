package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
@Composable
fun ExerciseRenderer(exercise: Exercise){
    Row (horizontalArrangement = Arrangement.SpaceBetween,
        modifier = Modifier
            .fillMaxWidth()
    ){
        Text(
            modifier = Modifier.weight(1f),
            text = exercise.name
        )
        for (set in exercise.sets){
            Column( horizontalAlignment = Alignment.End) {
                when(set){
                    is WeightSet -> {
                        Text(
                            text = "Reps: ${set.reps}"
                        )
                        Spacer(modifier= Modifier.height(5.dp))
                        Text(
                            text = "Weight: ${set.weight}kg"
                        )
                    }
                    is BodyWeightSet -> {
                        Text(
                            text = "Reps: ${set.reps}"
                        )
                    }
                    is TimedDurationSet -> {
                        Text(
                            text = "Duration: ${set.timeInMillis/1000}s"
                        )
                    }
                    is EnduranceSet -> {
                        Text(
                            text = "Duration: ${set.timeInMillis/1000}s"
                        )
                    }
                }
            }
        }
    }
}