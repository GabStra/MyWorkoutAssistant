package com.gabstra.myworkoutassistant.composables

import android.annotation.SuppressLint
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
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
import androidx.wear.compose.material3.lazy.ResponsiveTransformationSpec
import androidx.wear.compose.material3.lazy.TransformationVariableSpec
import androidx.wear.compose.material3.lazy.rememberTransformationSpec
import androidx.wear.compose.material3.lazy.transformedHeight
import androidx.wear.tooling.preview.devices.WearDevices
import com.gabstra.myworkoutassistant.presentation.theme.baseline
import com.gabstra.myworkoutassistant.presentation.theme.darkScheme
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.MediumLighterGray
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.workout.model.IncompleteWorkout
import com.gabstra.myworkoutassistant.shared.workout.recovery.CalibrationRecoveryChoice
import com.gabstra.myworkoutassistant.shared.workout.recovery.RecoveryPromptUiState
import com.gabstra.myworkoutassistant.shared.workout.recovery.RecoveryResumeOptions
import com.gabstra.myworkoutassistant.shared.workout.recovery.TimerRecoveryChoice
import com.gabstra.myworkoutassistant.shared.workout.ui.IncompleteWorkoutStrings
import java.time.Duration
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.format.DateTimeFormatter
import java.util.Locale.getDefault
import java.util.UUID

@Composable
internal fun RecoveryDialog(
    show: Boolean,
    workout: IncompleteWorkout?,
    uiState: RecoveryPromptUiState,
    onDismiss: () -> Unit,
    onResume: (IncompleteWorkout, RecoveryResumeOptions) -> Unit,
    onDiscard: (IncompleteWorkout) -> Unit
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
                                text = IncompleteWorkoutStrings.SINGULAR,
                                textAlign = TextAlign.Center,
                                style = MaterialTheme.typography.titleLarge,
                                color = MaterialTheme.colorScheme.onBackground
                            )
                        }
                    }

                    item {
                        RecoveryBodyText(
                            text = IncompleteWorkoutStrings.RECOVERY_RESUME_OR_DISCARD_BODY,
                            modifier = Modifier
                                .fillMaxWidth()
                                .transformedHeight(this, spec)
                                .graphicsLayer { with(spec) { applyContainerTransformation(scrollProgress) } }
                        )
                    }

                    item {
                        Box(
                            modifier = Modifier
                                .fillMaxWidth()
                                .transformedHeight(this, spec)
                                .graphicsLayer { with(spec) { applyContainerTransformation(scrollProgress) } }
                        ) {
                            Column(
                                modifier = Modifier.graphicsLayer {
                                    with(spec) { applyContentTransformation(scrollProgress) }
                                }
                            ) {
                                RecoveryInfoBlock(
                                    entries = buildList {
                                        add("Workout" to resolvedWorkoutName)
                                        if (resolvedExerciseName.isNotBlank()) {
                                            add("Exercise" to resolvedExerciseName)
                                        }
                                        if (startedText.isNotEmpty()) {
                                            add("Started" to startedText)
                                        }
                                        if (elapsedText.isNotEmpty()) {
                                            add("Elapsed" to elapsedText)
                                        }
                                    }
                                )
                            }
                        }
                    }

                    if (showTimerChoice) {
                        item {
                            Spacer(modifier = Modifier.height(10.dp))
                        }
                        item {
                            RecoverySectionHeader(
                                text = IncompleteWorkoutStrings.RECOVERY_SECTION_TIMER,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec)
                                    .graphicsLayer { with(spec) { applyContainerTransformation(scrollProgress) } }
                            )
                        }
                        item {
                            RecoveryChoiceButton(
                                modifier = Modifier.transformedHeight(this, spec),
                                transformation = SurfaceTransformation(spec),
                                contentDescription = "Recovery timer continue option",
                                text = "Continue",
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
                                modifier = Modifier.transformedHeight(this, spec),
                                transformation = SurfaceTransformation(spec),
                                contentDescription = "Recovery timer restart option",
                                text = "Restart",
                                colors = selectedRecoveryButtonColors(
                                    selected = timerChoice == TimerRecoveryChoice.RESTART
                                ),
                                onClick = {
                                    timerChoice = TimerRecoveryChoice.RESTART
                                    resumeWithChoices(TimerRecoveryChoice.RESTART, calibrationChoice)
                                }
                            )
                        }
                        if(!showCalibrationChoice){
                            item {
                                Spacer(modifier = Modifier.height(10.dp))
                            }
                        }
                    }

                    if (showCalibrationChoice) {
                        item {
                            Spacer(modifier = Modifier.height(10.dp))
                        }
                        item {
                            RecoverySectionHeader(
                                text = IncompleteWorkoutStrings.RECOVERY_SECTION_CALIBRATION,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec)
                                    .graphicsLayer { with(spec) { applyContainerTransformation(scrollProgress) } }
                            )
                        }
                        item {
                            RecoveryChoiceButton(
                                modifier = Modifier.transformedHeight(this, spec),
                                transformation = SurfaceTransformation(spec),
                                contentDescription = "Recovery calibration continue option",
                                text = "Continue",
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
                                modifier = Modifier.transformedHeight(this, spec),
                                transformation = SurfaceTransformation(spec),
                                contentDescription = "Recovery calibration restart option",
                                text = "Restart",
                                colors = selectedRecoveryButtonColors(
                                    selected = calibrationChoice == CalibrationRecoveryChoice.RESTART
                                ),
                                onClick = {
                                    calibrationChoice = CalibrationRecoveryChoice.RESTART
                                    resumeWithChoices(timerChoice, CalibrationRecoveryChoice.RESTART)
                                }
                            )
                        }
                        item {
                            Spacer(modifier = Modifier.height(10.dp))
                        }
                    }

                    if (showResumeButton) {
                        item {
                            RecoveryChoiceButton(
                                modifier = Modifier.transformedHeight(this, spec),
                                transformation = SurfaceTransformation(spec),
                                contentDescription = "Recovery resume action",
                                text = "Resume",
                                colors = androidx.wear.compose.material3.ButtonDefaults.buttonColors(),
                                onClick = {
                                    resumeWithChoices(timerChoice, calibrationChoice)
                                }
                            )
                        }
                    }

                    item {
                        RecoveryChoiceButton(
                            modifier = Modifier.transformedHeight(this, spec),
                            transformation = SurfaceTransformation(spec),
                            contentDescription = "Recovery dismiss action",
                            text = "Dismiss",
                            onClick = onDismiss
                        )
                    }

                    item {
                        CancelRecoveryChoiceButton(
                            modifier = Modifier.transformedHeight(this, spec),
                            transformation = SurfaceTransformation(spec),
                            contentDescription = "Recovery discard action",
                            text = IncompleteWorkoutStrings.DISCARD_BUTTON,
                            onClick = { onDiscard(workout) }
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun RecoveryInfoBlock(
    entries: List<Pair<String, String>>,
    modifier: Modifier = Modifier
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 10.dp)
            .padding(vertical = 5.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        entries.forEach { (label, value) ->
            Column(
                modifier = Modifier.fillMaxWidth(),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(2.5.dp)
            ) {
                Text(
                    text = label.uppercase(getDefault()),
                    modifier = Modifier.fillMaxWidth(),
                    style = workoutPagerTitleTextStyle(),
                    color = MaterialTheme.colorScheme.onBackground,
                    textAlign = TextAlign.Center
                )
                Text(
                    text = value,
                    modifier = Modifier.fillMaxWidth(),
                    style = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.SemiBold),
                    color = MaterialTheme.colorScheme.onBackground,
                    textAlign = TextAlign.Center
                )
            }
        }
    }
}

@Composable
private fun RecoveryBodyText(
    text: String,
    modifier: Modifier = Modifier
) {
    Box(
        modifier = modifier.padding(bottom = 5.dp)
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
private fun RecoverySectionHeader(
    text: String,
    modifier: Modifier = Modifier
) {
    Text(
        text = text.uppercase(getDefault()),
        modifier = modifier.padding(horizontal = 25.dp),
        style = workoutPagerTitleTextStyle(),
        color = MaterialTheme.colorScheme.onBackground,
        textAlign = TextAlign.Center
    )
}

@Composable
private fun RecoveryChoiceButton(
    modifier: Modifier = Modifier,
    transformation: SurfaceTransformation? = null,
    contentDescription: String,
    text: String,
    colors: androidx.wear.compose.material3.ButtonColors = androidx.wear.compose.material3.ButtonDefaults.filledTonalButtonColors(),
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
private fun OutlinedRecoveryChoiceButton(
    modifier: Modifier = Modifier,
    transformation: SurfaceTransformation? = null,
    contentDescription: String,
    text: String,
    onClick: () -> Unit
) {
    OutlinedButtonWithText(
        modifier = modifier
            .semantics { this.contentDescription = contentDescription }
            .fillMaxWidth(),
        transformation = transformation,
        text = text,
        onClick = onClick
    )
}

@Composable
private fun CancelRecoveryChoiceButton(
    modifier: Modifier = Modifier,
    transformation: SurfaceTransformation? = null,
    contentDescription: String,
    text: String,
    onClick: () -> Unit
) {
    CancelButtonWithText(
        modifier = modifier
            .semantics { this.contentDescription = contentDescription }
            .fillMaxWidth(),
        transformation = transformation,
        text = text,
        onClick = onClick
    )
}

@Composable
private fun selectedRecoveryButtonColors(selected: Boolean): androidx.wear.compose.material3.ButtonColors {
    return if (selected){
        androidx.wear.compose.material3.ButtonDefaults.buttonColors()
    } else {
        androidx.wear.compose.material3.ButtonDefaults.filledTonalButtonColors()
    }
}

@SuppressLint("DefaultLocale")
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

@Preview(device = WearDevices.LARGE_ROUND, showBackground = true)
@Composable
private fun RecoveryDialogPreview() {
    val previewStartedAt = LocalDateTime.of(2026, 4, 7, 18, 15)
    MaterialTheme(
        colorScheme = darkScheme,
        typography = baseline
    ) {
        RecoveryDialog(
            show = true,
            workout = IncompleteWorkout(
                workoutHistory = WorkoutHistory(
                    id = UUID.fromString("11111111-1111-1111-1111-111111111111"),
                    workoutId = UUID.fromString("22222222-2222-2222-2222-222222222222"),
                    date = LocalDate.of(2026, 4, 7),
                    time = LocalTime.of(18, 15),
                    startTime = previewStartedAt,
                    duration = 4_582,
                    heartBeatRecords = emptyList(),
                    isDone = false,
                    hasBeenSentToHealth = false,
                    globalId = UUID.fromString("33333333-3333-3333-3333-333333333333")
                ),
                workoutName = "Push Day A",
                workoutId = UUID.fromString("22222222-2222-2222-2222-222222222222")
            ),
            uiState = RecoveryPromptUiState(
                workoutName = "Push Day A",
                exerciseName = "Incline Dumbbell Press",
                workoutStartTime = previewStartedAt,
                showTimerOptions = true,
                showCalibrationOptions = true
            ),
            onDismiss = {},
            onResume = { _, _ -> },
            onDiscard = {}
        )
    }
}
