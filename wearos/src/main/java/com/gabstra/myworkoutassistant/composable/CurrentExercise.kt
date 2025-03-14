package com.gabstra.myworkoutassistant.composable

import androidx.compose.runtime.Composable
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState

@Composable
fun CurrentExercise(
    viewModel: AppViewModel,
    state: WorkoutState.Set,
){
    val exerciseIndex = viewModel.setsByExerciseId.keys.indexOf(state.exerciseId)
    val exerciseCount = viewModel.setsByExerciseId.keys.count()

    Text(
        textAlign = TextAlign.Center,
        text = "${exerciseIndex + 1}/${exerciseCount}",
        style = MaterialTheme.typography.caption1.copy(
            fontWeight = FontWeight.Bold
        )
    )
}