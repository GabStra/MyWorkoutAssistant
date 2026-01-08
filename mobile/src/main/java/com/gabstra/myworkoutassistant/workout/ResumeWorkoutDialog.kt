package com.gabstra.myworkoutassistant.workout

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.composables.StandardDialog
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import java.time.format.DateTimeFormatter
import java.util.UUID

@Composable
fun ResumeWorkoutDialog(
    show: Boolean,
    incompleteWorkouts: List<WorkoutViewModel.IncompleteWorkout>,
    onDismiss: () -> Unit,
    onResumeWorkout: (UUID) -> Unit
) {
    if (show && incompleteWorkouts.isNotEmpty()) {
        StandardDialog(
            onDismissRequest = onDismiss,
            title = "Resume Workout",
            body = {
                Text(
                    text = "You have incomplete workouts. Select one to resume:",
                    textAlign = TextAlign.Center,
                    style = MaterialTheme.typography.bodyLarge,
                    modifier = Modifier.padding(bottom = 16.dp)
                )
                
                LazyColumn(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height((incompleteWorkouts.size * 80).coerceAtMost(400).dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    items(incompleteWorkouts) { incompleteWorkout ->
                        Button(
                            modifier = Modifier.fillMaxWidth(),
                            onClick = {
                                onResumeWorkout(incompleteWorkout.workoutId)
                            }
                        ) {
                            Column(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalAlignment = Alignment.CenterHorizontally
                            ) {
                                Text(
                                    text = incompleteWorkout.workoutName,
                                    textAlign = TextAlign.Center,
                                    style = MaterialTheme.typography.titleMedium
                                )
                                
                                Spacer(modifier = Modifier.height(4.dp))
                                
                                Text(
                                    text = incompleteWorkout.workoutHistory.startTime.format(
                                        DateTimeFormatter.ofPattern("MMM dd, yyyy HH:mm")
                                    ),
                                    textAlign = TextAlign.Center,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.7f)
                                )
                            }
                        }
                    }
                }
            },
            showConfirm = false,
            dismissText = "Cancel",
            onDismissButton = onDismiss
        )
    }
}

