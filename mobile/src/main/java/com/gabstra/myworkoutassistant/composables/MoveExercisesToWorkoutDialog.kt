package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.PressInteraction
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.verticalColumnScrollbar
import com.gabstra.myworkoutassistant.composables.DialogTextButton

@Composable
fun MoveExercisesToWorkoutDialog(
    show: Boolean,
    onDismiss: () -> Unit,
    workouts: List<Workout>,
    currentWorkout: Workout,
    onMove: (Workout) -> Unit
) {
    if (show) {
        val scrollState = rememberScrollState()

        AlertDialog(
            onDismissRequest = onDismiss,
            title = { Text("Move to Workout") },
            text = {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 5.dp)
                        .padding(vertical = 10.dp)
                        .verticalColumnScrollbar(scrollState)
                        .verticalScroll(scrollState),
                    verticalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    // Only show other workouts, not the current one
                    val targetWorkouts = workouts.filter { it.id != currentWorkout.id }

                    if (targetWorkouts.isEmpty()) {
                        Text(
                            text = "No other workouts available to move to.",
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            style = MaterialTheme.typography.bodyMedium
                        )
                    } else {
                        targetWorkouts.forEach { targetWorkout ->
                            val interactionSource = remember { MutableInteractionSource() }
                            val interactions = interactionSource.interactions
                            val isPressed = interactions.collectAsState(initial = null).value is PressInteraction.Press
                            
                            val backgroundColor = MaterialTheme.colorScheme.surfaceVariant
                            val textColor = MaterialTheme.colorScheme.onSurfaceVariant
                            val backgroundColorPressed = lerp(backgroundColor, textColor, 0.15f)
                            val textColorPressed = lerp(textColor, backgroundColor, 0.15f)
                            
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(8.dp))
                                    .background(
                                        if (isPressed) backgroundColorPressed else backgroundColor
                                    )
                                    .clickable(
                                        interactionSource = interactionSource,
                                        indication = null,
                                        onClick = {
                                            onMove(targetWorkout)
                                            onDismiss()
                                        }
                                    )
                                    .padding(16.dp),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Text(
                                    text = targetWorkout.name,
                                    color = if (isPressed) textColorPressed else textColor,
                                    style = MaterialTheme.typography.bodyLarge
                                )
                            }
                        }
                    }
                }
            },
            confirmButton = {},
            dismissButton = {
                DialogTextButton(
                    text = "Cancel",
                    onClick = onDismiss
                )
            }
        )
    }
}

