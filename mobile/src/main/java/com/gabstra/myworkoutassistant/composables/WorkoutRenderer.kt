package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Divider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.ExerciseGroup

@Composable
fun WorkoutRenderer(workout: Workout){
    Column{
        for (workoutComponent in workout.workoutComponents) {
            Row(
                modifier = Modifier
                    .padding(10.dp),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically
            ){
                Text(
                    modifier = Modifier
                        .weight(1f)
                        .basicMarquee(iterations = Int.MAX_VALUE),
                    text = workoutComponent.name,
                    style = MaterialTheme.typography.bodyMedium,
                    color = Color.White.copy(alpha = .6f),
                )
                Spacer(modifier = Modifier.width(10.dp))
                when (workoutComponent) {
                    is Exercise -> ExerciseRenderer(exercise = workoutComponent)
                    is ExerciseGroup -> ExerciseGroupRenderer(exerciseGroup = workoutComponent)
                }
            }
        }
    }
}