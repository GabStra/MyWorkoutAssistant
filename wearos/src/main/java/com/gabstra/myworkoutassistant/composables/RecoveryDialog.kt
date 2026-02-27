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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import androidx.wear.compose.material3.ListHeader
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.ScrollIndicator
import androidx.wear.compose.material3.ScrollIndicatorDefaults
import androidx.wear.compose.material3.SurfaceTransformation
import androidx.wear.compose.material3.Text
import androidx.wear.compose.material3.lazy.rememberTransformationSpec
import androidx.wear.compose.material3.lazy.transformedHeight
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.workout.model.InterruptedWorkout
import com.gabstra.myworkoutassistant.shared.workout.recovery.CalibrationRecoveryChoice
import com.gabstra.myworkoutassistant.shared.workout.recovery.RecoveryPromptUiState
import com.gabstra.myworkoutassistant.shared.workout.recovery.RecoveryResumeOptions
import com.gabstra.myworkoutassistant.shared.workout.recovery.TimerRecoveryChoice
import com.gabstra.myworkoutassistant.shared.workout.ui.InterruptedWorkoutCopy
import java.time.Duration
import java.time.format.DateTimeFormatter

@Composable
internal fun RecoveryDialog(
    show: Boolean,
    workout: InterruptedWorkout?,
    uiState: RecoveryPromptUiState,
    onDismiss: () -> Unit,
    onResume: (InterruptedWorkout, RecoveryResumeOptions) -> Unit,
    onDiscard: (InterruptedWorkout) -> Unit
) {
    if (!show || workout == null) return

    val showTimerChoice = uiState.showTimerOptions
    val showCalibrationChoice = uiState.showCalibrationOptions
    val showResumeButton = uiState.showResumeButton
    val resolvedWorkoutName = uiState.displayName.ifBlank { workout.workoutName }
    val startedText = uiState.workoutStartTime?.format(
        DateTimeFormatter.ofPattern("EEE, dd MMM yyyy HH:mm")
    ).orEmpty()
    val elapsedText = formatElapsedDuration(workout.workoutHistory.duration)
    var timerChoice by remember(workout.workoutHistory.id) { mutableStateOf(TimerRecoveryChoice.CONTINUE) }
    var calibrationChoice by remember(workout.workoutHistory.id) { mutableStateOf(CalibrationRecoveryChoice.CONTINUE) }
    val resumeWithChoices: (TimerRecoveryChoice, CalibrationRecoveryChoice) -> Unit = { timer, calibration ->
        onResume(
            workout,
            RecoveryResumeOptions(
                timerChoice = timer,
                calibrationChoice = calibration
            )
        )
    }

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
                    contentPadding = contentPadding,
                    state = state
                ) {
                    item {
                        ListHeader(
                            modifier = Modifier
                                .fillMaxWidth()
                                .transformedHeight(this, spec),
                            transformation = SurfaceTransformation(spec)
                        ) {
                            Text(
                                text = InterruptedWorkoutCopy.SINGULAR,
                                textAlign = TextAlign.Center,
                                style = MaterialTheme.typography.titleLarge,
                                color = MaterialTheme.colorScheme.onBackground
                            )
                        }
                    }

                    item {
                        Box(
                            modifier = Modifier
                                .fillMaxWidth()
                                .transformedHeight(this, spec)
                                .graphicsLayer { with(spec) { applyContainerTransformation(scrollProgress) } }
                                .padding(bottom = 10.dp)
                        ) {
                            Column(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(horizontal = 12.dp)
                            ) {
                                Text(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .graphicsLayer { with(spec) { applyContentTransformation(scrollProgress) } },
                                    text = "Workout",
                                    textAlign = TextAlign.Center,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onBackground
                                )

                                Text(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .graphicsLayer { with(spec) { applyContentTransformation(scrollProgress) } },
                                    text = resolvedWorkoutName,
                                    textAlign = TextAlign.Center,
                                    style = MaterialTheme.typography.titleMedium,
                                    color = MaterialTheme.colorScheme.secondary
                                )

                                Spacer(Modifier.height(5.dp))

                                Text(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .graphicsLayer { with(spec) { applyContentTransformation(scrollProgress) } },
                                    text = "Started",
                                    textAlign = TextAlign.Center,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onBackground
                                )

                                Text(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .graphicsLayer { with(spec) { applyContentTransformation(scrollProgress) } },
                                    text = startedText,
                                    textAlign = TextAlign.Center,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.secondary
                                )

                                if (elapsedText.isNotEmpty()) {
                                    Spacer(Modifier.height(5.dp))

                                    Text(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .graphicsLayer { with(spec) { applyContentTransformation(scrollProgress) } },
                                        text = "Elapsed",
                                        textAlign = TextAlign.Center,
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onBackground
                                    )

                                    Text(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .graphicsLayer { with(spec) { applyContentTransformation(scrollProgress) } },
                                        text = elapsedText,
                                        textAlign = TextAlign.Center,
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.secondary
                                    )
                                }
                            }
                        }
                    }

                    if (showTimerChoice) {
                        item {
                            Box(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(vertical = 2.dp)
                                    .transformedHeight(this, spec)
                                    .graphicsLayer { with(spec) { applyContainerTransformation(scrollProgress) } }
                            ) {
                                Text(
                                    text = "Timer recovery",
                                    textAlign = TextAlign.Center,
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = MaterialTheme.colorScheme.onBackground,
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .graphicsLayer { with(spec) { applyContentTransformation(scrollProgress) } }
                                )
                            }
                        }

                        item {
                            ButtonWithText(
                                modifier = Modifier
                                    .semantics { contentDescription = "Recovery timer continue option" }
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec),
                                transformation = SurfaceTransformation(spec),
                                text = if (timerChoice == TimerRecoveryChoice.CONTINUE) "Continue timer (selected)" else "Continue timer",
                                onClick = {
                                    timerChoice = TimerRecoveryChoice.CONTINUE
                                    resumeWithChoices(TimerRecoveryChoice.CONTINUE, calibrationChoice)
                                }
                            )
                        }

                        item {
                            ButtonWithText(
                                modifier = Modifier
                                    .semantics { contentDescription = "Recovery timer restart option" }
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec),
                                transformation = SurfaceTransformation(spec),
                                text = if (timerChoice == TimerRecoveryChoice.RESTART) "Restart timer (selected)" else "Restart timer",
                                onClick = {
                                    timerChoice = TimerRecoveryChoice.RESTART
                                    resumeWithChoices(TimerRecoveryChoice.RESTART, calibrationChoice)
                                }
                            )
                        }
                    }

                    if (showCalibrationChoice) {
                        item {
                            Box(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(vertical = 2.dp)
                                    .transformedHeight(this, spec)
                                    .graphicsLayer { with(spec) { applyContainerTransformation(scrollProgress) } }
                            ) {
                                Text(
                                    text = "Calibration recovery",
                                    textAlign = TextAlign.Center,
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = MaterialTheme.colorScheme.onBackground,
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .graphicsLayer { with(spec) { applyContentTransformation(scrollProgress) } }
                                )
                            }
                        }

                        item {
                            ButtonWithText(
                                modifier = Modifier
                                    .semantics { contentDescription = "Recovery calibration continue option" }
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec),
                                transformation = SurfaceTransformation(spec),
                                text = if (calibrationChoice == CalibrationRecoveryChoice.CONTINUE) "Continue calibration (selected)" else "Continue calibration",
                                onClick = {
                                    calibrationChoice = CalibrationRecoveryChoice.CONTINUE
                                    resumeWithChoices(timerChoice, CalibrationRecoveryChoice.CONTINUE)
                                }
                            )
                        }

                        item {
                            ButtonWithText(
                                modifier = Modifier
                                    .semantics { contentDescription = "Recovery calibration restart option" }
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec),
                                transformation = SurfaceTransformation(spec),
                                text = if (calibrationChoice == CalibrationRecoveryChoice.RESTART) "Restart calibration (selected)" else "Restart calibration",
                                onClick = {
                                    calibrationChoice = CalibrationRecoveryChoice.RESTART
                                    resumeWithChoices(timerChoice, CalibrationRecoveryChoice.RESTART)
                                }
                            )
                        }
                    }

                    if (showResumeButton) {
                        item {
                            ButtonWithText(
                                modifier = Modifier
                                    .semantics { contentDescription = "Recovery resume action" }
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec),
                                transformation = SurfaceTransformation(spec),
                                text = "Resume",
                                onClick = {
                                    resumeWithChoices(timerChoice, calibrationChoice)
                                }
                            )
                        }
                    }

                    item {
                        ButtonWithText(
                            modifier = Modifier
                                .semantics { contentDescription = "Recovery discard action" }
                                .fillMaxWidth()
                                .transformedHeight(this, spec),
                            transformation = SurfaceTransformation(spec),
                            text = "Discard",
                            onClick = { onDiscard(workout) }
                        )
                    }

                    item {
                        ButtonWithText(
                            modifier = Modifier
                                .semantics { contentDescription = "Recovery dismiss action" }
                                .fillMaxWidth()
                                .transformedHeight(this, spec),
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

private fun formatElapsedDuration(durationSeconds: Int): String {
    if (durationSeconds <= 0) return ""
    val duration = Duration.ofSeconds(durationSeconds.toLong())
    val totalHours = duration.toHours()
    val minutes = duration.toMinutesPart()
    val seconds = duration.toSecondsPart()
    return if (totalHours > 0) {
        String.format("%dh %02dm", totalHours, minutes)
    } else {
        String.format("%dm %02ds", minutes, seconds)
    }
}
