package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Divider
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.ExerciseRenderer
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.ExerciseGroup

@Composable
fun ExerciseGroupRenderer(exerciseGroup: ExerciseGroup) {
    for (workoutComponent in exerciseGroup.workoutComponents) {
        Row(
            horizontalArrangement = Arrangement.SpaceBetween,
            modifier = Modifier
                .fillMaxWidth()
        ) {
            when (workoutComponent) {
                is Exercise -> ExerciseRenderer(workoutComponent)
                is ExerciseGroup -> {
                    Text(
                        modifier = Modifier.weight(1f),
                        text = workoutComponent.name
                    )
                }
            }
        }
        if (workoutComponent is ExerciseGroup) ExerciseGroupRenderer(workoutComponent)
        if (workoutComponent != exerciseGroup.workoutComponents.last()) Divider(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 10.dp), thickness = 1.dp, color = Color.White
        )
    }
}