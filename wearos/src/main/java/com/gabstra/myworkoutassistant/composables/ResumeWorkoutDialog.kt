package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.items
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import androidx.wear.compose.material3.Button
import androidx.wear.compose.material3.ListHeader
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.SurfaceTransformation
import androidx.wear.compose.material3.Text
import androidx.wear.compose.material3.lazy.rememberTransformationSpec
import androidx.wear.compose.material3.lazy.transformedHeight
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import java.time.format.DateTimeFormatter
import java.util.UUID

@Composable
fun ResumeWorkoutDialog(
    show: Boolean,
    hapticsViewModel: HapticsViewModel,
    incompleteWorkouts: List<WorkoutViewModel.IncompleteWorkout>,
    onDismiss: () -> Unit,
    onResumeWorkout: (UUID) -> Unit
) {
    if (show && incompleteWorkouts.isNotEmpty()) {
        Dialog(
            onDismissRequest = onDismiss,
            properties = DialogProperties(
                dismissOnBackPress = true,
                dismissOnClickOutside = false
            )
        ) {
            Box(
                modifier = Modifier
                    .background(MaterialTheme.colorScheme.background)
                    .fillMaxSize()
            ) {
                val state = rememberTransformingLazyColumnState()
                val spec = rememberTransformationSpec()

                ScreenScaffold(
                    scrollState = state
                ) { contentPadding ->
                    TransformingLazyColumn(
                        contentPadding = contentPadding,
                        state = state
                    ) {
                        item {
                            ListHeader(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec).animateItem(),
                                transformation = SurfaceTransformation(spec)
                            ) {
                                Text(
                                    text = "Resume Workout",
                                    textAlign = TextAlign.Center,
                                    style = MaterialTheme.typography.titleMedium,
                                    color = MaterialTheme.colorScheme.onBackground
                                )
                            }
                        }

                        item {
                            Text(
                                text = "Select workout to resume:",
                                textAlign = TextAlign.Center,
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onBackground,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(horizontal = 8.dp, vertical = 4.dp)
                            )
                        }

                        items(incompleteWorkouts) { incompleteWorkout ->
                            Button(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec).animateItem(),
                                transformation = SurfaceTransformation(spec),
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

                        item {
                            Spacer(modifier = Modifier.height(8.dp))
                        }

                        item {
                            ButtonWithText(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec).animateItem(),
                                transformation = SurfaceTransformation(spec),
                                text = "Dismiss",
                                onClick = onDismiss
                            )
                        }
                    }
                }
            }
        }
    }
}
