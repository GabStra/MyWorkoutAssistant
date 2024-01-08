package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Card
import androidx.compose.material3.Divider
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.ExerciseGroup

@Composable
fun WorkoutRenderer(workout: Workout){
    Card(
        modifier= Modifier.padding(10.dp)
    ){
        for(workoutComponent in workout.workoutComponents){
            Row(){
                Text(text = workoutComponent.name, modifier = Modifier.padding(8.dp))
                when (workoutComponent) {
                    is Exercise -> ExerciseRenderer(workoutComponent)
                    is ExerciseGroup -> ExerciseGroupRenderer(workoutComponent)
                }
            }
            if(workoutComponent != workout.workoutComponents.last()) Divider( modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 10.dp),thickness = 1.dp, color = Color.White)
        }
    }
}