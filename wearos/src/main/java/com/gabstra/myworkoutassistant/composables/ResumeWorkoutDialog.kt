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
import androidx.wear.compose.material3.ScrollIndicator
import androidx.wear.compose.material3.ScrollIndicatorDefaults
import androidx.wear.compose.material3.SurfaceTransformation
import androidx.wear.compose.material3.Text
import androidx.wear.compose.material3.lazy.rememberTransformationSpec
import androidx.wear.compose.material3.lazy.transformedHeight
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import com.gabstra.myworkoutassistant.shared.workout.ui.InterruptedWorkoutCopy
import java.time.format.DateTimeFormatter

@Composable
fun ResumeWorkoutDialog(
    show: Boolean,
    hapticsViewModel: HapticsViewModel,
    incompleteWorkouts: List<WorkoutViewModel.IncompleteWorkout>,
    onDismiss: () -> Unit,
    onResumeWorkout: (WorkoutViewModel.IncompleteWorkout) -> Unit
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
                    scrollState = state,
                    scrollIndicator = {
                        ScrollIndicator(
                            state = state,
                            colors = ScrollIndicatorDefaults.colors(
                                indicatorColor = MaterialTheme.colorScheme.onBackground,
                                trackColor = MediumDarkGray
                            )
                        )
                    }
                ) { contentPadding ->
                    TransformingLazyColumn(
                        modifier = Modifier.padding(horizontal = 10.dp),
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
                                    style = MaterialTheme.typography.titleLarge,
                                    color = MaterialTheme.colorScheme.onBackground
                                )
                            }
                        }

                        item {
                            Text(
                                text = "${InterruptedWorkoutCopy.PLURAL}:",
                                textAlign = TextAlign.Center,
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onBackground,
                                modifier = Modifier.fillMaxWidth().padding(vertical = 5.dp)
                            )
                        }

                        items(incompleteWorkouts) { incompleteWorkout ->
                            Button(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec).animateItem(),
                                transformation = SurfaceTransformation(spec),
                                onClick = {
                                    onResumeWorkout(incompleteWorkout)
                                }
                            ) {
                                Column(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalAlignment = Alignment.CenterHorizontally
                                ) {
                                    Text(
                                        modifier = Modifier.fillMaxWidth(),
                                        text = incompleteWorkout.workoutName,
                                        textAlign = TextAlign.Center,
                                        style = MaterialTheme.typography.titleMedium,
                                        color = MaterialTheme.colorScheme.onPrimary
                                    )

                                    Spacer(modifier = Modifier.height(5.dp))

                                    Text(
                                        modifier = Modifier.fillMaxWidth(),
                                        text = incompleteWorkout.workoutHistory.startTime.format(
                                            DateTimeFormatter.ofPattern("dd MMM yyyy, HH:mm")
                                        ),
                                        textAlign = TextAlign.Center,
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.7f)
                                    )
                                }
                            }
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
