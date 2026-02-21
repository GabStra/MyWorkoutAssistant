package com.gabstra.myworkoutassistant.workout

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.composables.AppPrimaryButton
import com.gabstra.myworkoutassistant.composables.StandardDialog
import com.gabstra.myworkoutassistant.shared.workout.model.InterruptedWorkout
import com.gabstra.myworkoutassistant.shared.workout.ui.InterruptedWorkoutCopy
import java.time.format.DateTimeFormatter

@Composable
fun ResumeWorkoutDialog(
    show: Boolean,
    interruptedWorkouts: List<InterruptedWorkout>,
    onDismiss: () -> Unit,
    onResumeWorkout: (InterruptedWorkout) -> Unit
) {
    if (show && interruptedWorkouts.isNotEmpty()) {
        StandardDialog(
            onDismissRequest = onDismiss,
            title = "Resume Workout",
            body = {
                Text(
                    text = InterruptedWorkoutCopy.RESUME_DIALOG_DESCRIPTION,
                    textAlign = TextAlign.Center,
                    style = MaterialTheme.typography.bodyLarge,
                    modifier = Modifier.padding(bottom = 16.dp)
                )
                
                LazyColumn(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height((interruptedWorkouts.size * 80).coerceAtMost(400).dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    items(interruptedWorkouts) { interruptedWorkout ->
                        AppPrimaryButton(
                            text = buildString {
                                append(interruptedWorkout.workoutName)
                                append("\n")
                                append(
                                    interruptedWorkout.workoutHistory.startTime.format(
                                        DateTimeFormatter.ofPattern("MMM dd, yyyy HH:mm")
                                    )
                                )
                            },
                            modifier = Modifier.fillMaxWidth(),
                            minHeight = 64.dp,
                            onClick = {
                                onResumeWorkout(interruptedWorkout)
                            }
                        )
                    }
                }
            },
            showConfirm = false,
            dismissText = "Cancel",
            onDismissButton = onDismiss
        )
    }
}

