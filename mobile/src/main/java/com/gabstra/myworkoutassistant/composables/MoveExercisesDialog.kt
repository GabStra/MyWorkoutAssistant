│package com.gabstra.myworkoutassistant.composables
│
│import androidx.compose.foundation.layout.Arrangement
│import androidx.compose.foundation.layout.Column
│import androidx.compose.foundation.layout.fillMaxWidth
│import androidx.compose.foundation.layout.padding
│import androidx.compose.material3.Button
│import androidx.compose.material3.MaterialTheme
│import androidx.compose.material3.Text
│import androidx.compose.runtime.Composable
│import androidx.compose.runtime.getValue
│import androidx.compose.runtime.mutableStateOf
│import androidx.compose.runtime.remember
│import androidx.compose.runtime.setValue
│import androidx.compose.ui.Modifier
│import androidx.compose.ui.unit.dp
│import com.gabstra.myworkoutassistant.AppViewModel
│import com.gabstra.myworkoutassistant.shared.Workout
│
│@Composable
│fun MoveExercisesDialog(
│    viewModel: AppViewModel,
│    sourceWorkoutId: UUID,
│    exerciseIds: List<UUID>,
│    onDismiss: () -> Unit
│) {
│    val workouts = viewModel.workouts
│    val sourceWorkout = workouts.find { it.id == sourceWorkoutId }!!
│    val exercisesToMove = sourceWorkout.workoutComponents
│        .filter { it.id in exerciseIds }
│        .map { it as Exercise }
│
│    var selectedTargetWorkout by remember { mutableStateOf<Workout?>(null) }
│
│    Column(
│        modifier = Modifier
│            .fillMaxWidth()
│            .padding(16.dp),
│        verticalArrangement = Arrangement.spacedBy(16.dp)
│    ) {
│        Text(
│            text = "Move ${exercisesToMove.size} exercise(s)",
│            style = MaterialTheme.typography.headlineSmall
│        )
│
│        WorkoutSelectionList(
│            workouts = workouts.filter { it.id != sourceWorkoutId },
│            selectedWorkout = selectedTargetWorkout,
│            onWorkoutSelected = { selectedTargetWorkout = it }
│        )
│
│        Button(
│            onClick = {
│                selectedTargetWorkout?.let { target ->
│                    viewModel.moveExercises(sourceWorkout, exercisesToMove, target)
│                    onDismiss()
│                }
│            },
│            modifier = Modifier.fillMaxWidth(),
│            enabled = selectedTargetWorkout != null
│        ) {
│            Text("Move to Selected Workout")
│        }
│
│        Button(
│            onClick = onDismiss,
│            modifier = Modifier.fillMaxWidth(),
│            colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.errorContainer)
│        ) {
│            Text("Cancel")
│        }
│    }
│}
