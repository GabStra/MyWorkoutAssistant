package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
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
import androidx.wear.compose.material3.ButtonDefaults
import androidx.wear.compose.material3.ListHeader
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.ScrollIndicator
import androidx.wear.compose.material3.ScrollIndicatorDefaults
import androidx.wear.compose.material3.SurfaceTransformation
import androidx.wear.compose.material3.Text
import androidx.wear.compose.material3.lazy.ResponsiveTransformationSpec
import androidx.wear.compose.material3.lazy.TransformationVariableSpec
import androidx.wear.compose.material3.lazy.rememberTransformationSpec
import androidx.wear.compose.material3.lazy.transformedHeight
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.MediumLighterGray
import com.gabstra.myworkoutassistant.shared.workout.model.InterruptedWorkout
import com.gabstra.myworkoutassistant.shared.workout.recovery.CalibrationRecoveryChoice
import com.gabstra.myworkoutassistant.shared.workout.recovery.RecoveryPromptUiState
import com.gabstra.myworkoutassistant.shared.workout.recovery.RecoveryResumeOptions
import com.gabstra.myworkoutassistant.shared.workout.recovery.TimerRecoveryChoice
import com.gabstra.myworkoutassistant.shared.workout.ui.InterruptedWorkoutCopy
import java.time.Duration
import java.time.format.DateTimeFormatter
import java.util.Locale.getDefault

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
    val resolvedWorkoutName = uiState.workoutName.ifBlank { workout.workoutName }
    val resolvedExerciseName = uiState.exerciseName
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
            dismissOnClickOutside = false,
            usePlatformDefaultWidth = false
        )
    ) {
        Box(
            modifier = Modifier
                .background(MaterialTheme.colorScheme.background)
                .fillMaxSize()
        ) {
            val state = rememberTransformingLazyColumnState()
            val spec = rememberTransformationSpec(
                ResponsiveTransformationSpec.smallScreen(
                    containerAlpha = TransformationVariableSpec(1f),
                    contentAlpha = TransformationVariableSpec(1f),
                    scale = TransformationVariableSpec(0.75f)
                ),
                ResponsiveTransformationSpec.largeScreen(
                    containerAlpha = TransformationVariableSpec(1f),
                    contentAlpha = TransformationVariableSpec(1f),
                    scale = TransformationVariableSpec(0.6f)
                )
            )

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
                    state = state,
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
                        RecoveryBodyText(
                            text = "Resume or discard this interrupted workout.",
                            modifier = Modifier
                                .fillMaxWidth()
                                .transformedHeight(this, spec)
                                .graphicsLayer { with(spec) { applyContainerTransformation(scrollProgress) } }
                        )
                    }

                    item {
                        RecoveryInfoBlock(
                            label = "Workout",
                            value = resolvedWorkoutName,
                            modifier = Modifier
                                .fillMaxWidth()
                                .transformedHeight(this, spec)
                                .graphicsLayer { with(spec) { applyContainerTransformation(scrollProgress) } }
                        )
                    }

                    if (resolvedExerciseName.isNotBlank()) {
                        item {
                            RecoveryInfoBlock(
                                label = "Exercise",
                                value = resolvedExerciseName,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec)
                                    .graphicsLayer { with(spec) { applyContainerTransformation(scrollProgress) } }
                            )
                        }
                    }

                    if (startedText.isNotEmpty()) {
                        item {
                            RecoveryInfoBlock(
                                label = "Started",
                                value = startedText,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec)
                                    .graphicsLayer { with(spec) { applyContainerTransformation(scrollProgress) } }
                            )
                        }
                    }

                    if (elapsedText.isNotEmpty()) {
                        item {
                            RecoveryInfoBlock(
                                label = "Elapsed",
                                value = elapsedText,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec)
                                    .graphicsLayer { with(spec) { applyContainerTransformation(scrollProgress) } }
                            )
                        }
                    }

                    if (showTimerChoice) {
                        item {
                            RecoverySectionLabel(
                                text = "Timer recovery",
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec)
                                    .graphicsLayer { with(spec) { applyContainerTransformation(scrollProgress) } }
                            )
                        }
                        item {
                            RecoveryChoiceButton(
                                modifier = Modifier.transformedHeight(this, spec) .graphicsLayer { with(spec) { applyContainerTransformation(scrollProgress) } },
                                transformation = SurfaceTransformation(spec),
                                contentDescription = "Recovery timer continue option",
                                text = "Continue timer",
                                colors = selectedRecoveryButtonColors(
                                    selected = timerChoice == TimerRecoveryChoice.CONTINUE
                                ),
                                onClick = {
                                    timerChoice = TimerRecoveryChoice.CONTINUE
                                    resumeWithChoices(TimerRecoveryChoice.CONTINUE, calibrationChoice)
                                }
                            )
                        }
                        item {
                            RecoveryChoiceButton(
                                modifier = Modifier.transformedHeight(this, spec) .graphicsLayer { with(spec) { applyContainerTransformation(scrollProgress) } },
                                transformation = SurfaceTransformation(spec),
                                contentDescription = "Recovery timer restart option",
                                text = "Restart timer",
                                colors = selectedRecoveryButtonColors(
                                    selected = timerChoice == TimerRecoveryChoice.RESTART
                                ),
                                onClick = {
                                    timerChoice = TimerRecoveryChoice.RESTART
                                    resumeWithChoices(TimerRecoveryChoice.RESTART, calibrationChoice)
                                }
                            )
                        }
                    }

                    if (showCalibrationChoice) {
                        item {
                            RecoverySectionLabel(
                                text = "Calibration recovery",
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec)
                                    .graphicsLayer { with(spec) { applyContainerTransformation(scrollProgress) } }
                            )
                        }
                        item {
                            RecoveryChoiceButton(
                                modifier = Modifier.transformedHeight(this, spec) .graphicsLayer { with(spec) { applyContainerTransformation(scrollProgress) } },
                                transformation = SurfaceTransformation(spec),
                                contentDescription = "Recovery calibration continue option",
                                text =  "Continue calibration",
                                colors = selectedRecoveryButtonColors(
                                    selected = calibrationChoice == CalibrationRecoveryChoice.CONTINUE
                                ),
                                onClick = {
                                    calibrationChoice = CalibrationRecoveryChoice.CONTINUE
                                    resumeWithChoices(timerChoice, CalibrationRecoveryChoice.CONTINUE)
                                }
                            )
                        }
                        item {
                            RecoveryChoiceButton(
                                modifier = Modifier.transformedHeight(this, spec) .graphicsLayer { with(spec) { applyContainerTransformation(scrollProgress) } },
                                transformation = SurfaceTransformation(spec),
                                contentDescription = "Recovery calibration restart option",
                                text = "Restart calibration",
                                colors = selectedRecoveryButtonColors(
                                    selected = calibrationChoice == CalibrationRecoveryChoice.RESTART
                                ),
                                onClick = {
                                    calibrationChoice = CalibrationRecoveryChoice.RESTART
                                    resumeWithChoices(timerChoice, CalibrationRecoveryChoice.RESTART)
                                }
                            )
                        }
                    }

                    if (showResumeButton) {
                        item {
                            RecoveryChoiceButton(
                                modifier = Modifier.transformedHeight(this, spec) .graphicsLayer { with(spec) { applyContainerTransformation(scrollProgress) } },
                                transformation = SurfaceTransformation(spec),
                                contentDescription = "Recovery resume action",
                                text = "Resume",
                                colors = ButtonDefaults.buttonColors(),
                                onClick = {
                                    resumeWithChoices(timerChoice, calibrationChoice)
                                }
                            )
                        }
                    }

                    item {
                        RecoveryChoiceButton(
                            modifier = Modifier.transformedHeight(this, spec) .graphicsLayer { with(spec) { applyContainerTransformation(scrollProgress) } },
                            transformation = SurfaceTransformation(spec),
                            contentDescription = "Recovery discard action",
                            text = "Discard",
                            colors = ButtonDefaults.filledTonalButtonColors(
                                containerColor = MaterialTheme.colorScheme.error,
                                contentColor = MaterialTheme.colorScheme.onError
                            ),
                            onClick = { onDiscard(workout) }
                        )
                    }

                    item {
                        RecoveryChoiceButton(
                            modifier = Modifier.transformedHeight(this, spec) .graphicsLayer { with(spec) { applyContainerTransformation(scrollProgress) } },
                            transformation = SurfaceTransformation(spec),
                            contentDescription = "Recovery dismiss action",
                            text = "Dismiss",
                            onClick = onDismiss
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun RecoveryInfoBlock(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
    valueColor: androidx.compose.ui.graphics.Color = MaterialTheme.colorScheme.onBackground
) {
    Box(
        modifier = modifier,
        contentAlignment = Alignment.Center
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 10.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(2.5.dp)
        ) {
            if (label.isNotEmpty()) {
                Text(
                    text = label.uppercase(getDefault()),
                    textAlign = TextAlign.Center,
                    style = MaterialTheme.typography.bodyExtraSmall,
                    color =  MaterialTheme.colorScheme.onBackground,
                    modifier = Modifier.fillMaxWidth()
                )
            }
            Text(
                text = value,
                textAlign = TextAlign.Center,
                style = MaterialTheme.typography.bodyLarge,
                color = valueColor,
                modifier = Modifier.fillMaxWidth()
            )
        }
    }


}

@Composable
private fun RecoveryBodyText(
    text: String,
    modifier: Modifier = Modifier
) {
    Box(
        modifier = modifier.padding(horizontal = 10.dp).padding(bottom = 5.dp)
    ){
        Text(
            text = text,
            textAlign = TextAlign.Center,
            style = MaterialTheme.typography.bodySmall,
            color = MediumLighterGray,
        )
    }
}

@Composable
private fun RecoverySectionLabel(
    text: String,
    modifier: Modifier = Modifier
) {
    Text(
        text = text,
        textAlign = TextAlign.Center,
        style = MaterialTheme.typography.bodyMedium,
        color = MaterialTheme.colorScheme.onBackground,
        modifier = modifier.padding(top = 4.dp)
    )
}

@Composable
private fun RecoveryChoiceButton(
    modifier: Modifier = Modifier,
    transformation: SurfaceTransformation? = null,
    contentDescription: String,
    text: String,
    colors: androidx.wear.compose.material3.ButtonColors = ButtonDefaults.filledTonalButtonColors(),
    onClick: () -> Unit
) {
    ButtonWithText(
        modifier = modifier
            .semantics { this.contentDescription = contentDescription }
            .fillMaxWidth(),
        transformation = transformation,
        text = text,
        colors = colors,
        onClick = onClick
    )
}

@Composable
private fun selectedRecoveryButtonColors(selected: Boolean): androidx.wear.compose.material3.ButtonColors {
    return if (selected){
        ButtonDefaults.buttonColors()
    } else {
        ButtonDefaults.filledTonalButtonColors()
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
