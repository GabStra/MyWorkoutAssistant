package com.gabstra.myworkoutassistant.screens

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Context
import android.widget.Toast
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.core.content.edit
import androidx.navigation.NavController
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import androidx.wear.tooling.preview.devices.WearDevices
import com.gabstra.myworkoutassistant.composables.ButtonWithText
import com.gabstra.myworkoutassistant.composables.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.composables.OutlinedButtonWithText
import com.gabstra.myworkoutassistant.composables.ProgressionSection
import com.gabstra.myworkoutassistant.composables.ScalableText
import com.gabstra.myworkoutassistant.composables.WearPrimaryButton
import com.gabstra.myworkoutassistant.composables.WorkoutPagerHeaderReservedHeight
import com.gabstra.myworkoutassistant.composables.rememberWearCoroutineScope
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.ExternalHeartRateDeviceController
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.SensorDataViewModel
import com.gabstra.myworkoutassistant.data.cancelWorkoutInProgressNotification
import com.gabstra.myworkoutassistant.presentation.theme.baseline
import com.gabstra.myworkoutassistant.presentation.theme.darkScheme
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureReviewStatus
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSegmentRecord
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.time.Duration
import java.time.LocalDateTime
import java.time.temporal.ChronoUnit

@SuppressLint("DefaultLocale")
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun WorkoutCompleteScreen(
    navController: NavController,
    viewModel: AppViewModel,
    state : WorkoutState.Completed,
    hrViewModel: SensorDataViewModel,
    hapticsViewModel: HapticsViewModel,
    externalHeartRateController: ExternalHeartRateDeviceController?
){
    val showNextDialog by viewModel.isCustomDialogOpen.collectAsState()
    val workout by viewModel.selectedWorkout
    val motionCaptureUiState by viewModel.motionCaptureUiState.collectAsState()
    val context = LocalContext.current

    val countDownTimer = remember { mutableIntStateOf(30) }
    var progressionDataCalculated by remember { mutableStateOf(false) }
    var progressionIsEmpty by remember { mutableStateOf<Boolean?>(null) }
    var completionSyncInitiated by remember { mutableStateOf(false) }
    var selectedReviewSegmentIndex by remember { mutableStateOf(0) }
    var selectedCandidateIndex by remember { mutableStateOf(0) }

    val scope = rememberWearCoroutineScope()
    var closeJob by remember { mutableStateOf<Job?>(null) }
    val reviewSession = motionCaptureUiState.latestReviewSession
    val reviewSegments = reviewSession?.segments.orEmpty()
    val activeReviewSegment = reviewSegments.getOrNull(selectedReviewSegmentIndex.coerceAtMost((reviewSegments.size - 1).coerceAtLeast(0)))

    LaunchedEffect(activeReviewSegment?.id) {
        selectedCandidateIndex = 0
    }

    fun startCloseJob() {
        closeJob?.cancel()
        closeJob = scope.launch {
            var remaining = countDownTimer.intValue

            while (remaining > 0 && isActive) {
                val now = LocalDateTime.now()
                val nextSecond = now.plusSeconds(1).truncatedTo(ChronoUnit.SECONDS)
                delay(Duration.between(now, nextSecond).toMillis())

                remaining--
                countDownTimer.intValue = remaining
            }

            if (isActive) {
                viewModel.clearCompletionPushCompleted()
                Toast.makeText(context, "Workout saved.", Toast.LENGTH_SHORT).show()
                (context as? Activity)?.finishAndRemoveTask()
            }
        }
    }

    // Run critical completion persistence immediately so next app launch does not show recovery.
    LaunchedEffect(Unit) {
        if (!completionSyncInitiated) {
            completionSyncInitiated = true

            if (!workout.usesExternalHeartRateDevice) {
                hrViewModel.stopMeasuringHeartRate()
            } else {
                externalHeartRateController?.disconnectFromDevice()
            }
            cancelWorkoutInProgressNotification(context)

            val prefs = context.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
            prefs.edit { putBoolean("isWorkoutInProgress", false) }

            viewModel.pushAndStoreWorkoutData(isDone = true, context = context, forceNotSend = false) {
                android.util.Log.d(
                    "WorkoutSync",
                    "SYNC_TRACE event=completion_force_send side=wear isDone=true"
                )
                viewModel.clearRecoveryCheckpoint()
                viewModel.deleteWorkoutRecord()
                viewModel.flushWorkoutSync()
            }
        }
    }

    // Defer UX-only side effects (haptics, sensors, notification) so they don't run on first frame.
    LaunchedEffect(Unit) {

        viewModel.setDimming(false)

        delay(500)
        hapticsViewModel.doShortImpulse()
    }

    // Start countdown when progression data is ready; sync runs independently in background.
    LaunchedEffect(progressionDataCalculated, progressionIsEmpty) {
        if (progressionDataCalculated && progressionIsEmpty != null) {
            // Set timer duration: 5 seconds if empty/null, 30 seconds if has data
            val timerDuration = if (progressionIsEmpty == true) 5 else 30
            countDownTimer.intValue = timerDuration
            startCloseJob()
        }
    }

    WorkoutCompleteScreenContent(
        workoutName = workout.name,
        countDownSeconds = countDownTimer.intValue,
        showCountdown = progressionDataCalculated,
        progressionContent = {
            ProgressionSection(
                modifier = Modifier.weight(1f),
                viewModel = viewModel,
                waitForCompletionPush = true,
                onProgressionDataCalculated = { isEmpty ->
                    if (!progressionDataCalculated) {
                        progressionDataCalculated = true
                        progressionIsEmpty = isEmpty
                    }
                }
            )
        },
        motionReviewContent = {
            if (reviewSession != null && activeReviewSegment != null) {
                MotionCaptureReviewPanel(
                    segment = activeReviewSegment,
                    segmentIndex = selectedReviewSegmentIndex,
                    segmentCount = reviewSegments.size,
                    candidateNames = reviewSession.session.exerciseCandidates.map { it.exerciseName },
                    selectedCandidateIndex = selectedCandidateIndex,
                    lastExportDirectory = motionCaptureUiState.lastExportDirectory,
                    onPreviousSegment = {
                        selectedReviewSegmentIndex = (selectedReviewSegmentIndex - 1).coerceAtLeast(0)
                    },
                    onNextSegment = {
                        selectedReviewSegmentIndex = (selectedReviewSegmentIndex + 1)
                            .coerceAtMost((reviewSegments.lastIndex).coerceAtLeast(0))
                    },
                    onNextCandidate = {
                        if (reviewSession.session.exerciseCandidates.isNotEmpty()) {
                            selectedCandidateIndex =
                                (selectedCandidateIndex + 1) % reviewSession.session.exerciseCandidates.size
                        }
                    },
                    onConfirm = {
                        scope.launch { viewModel.confirmMotionCaptureSegment(activeReviewSegment.id) }
                    },
                    onUseCandidate = {
                        val candidate = reviewSession.session.exerciseCandidates.getOrNull(selectedCandidateIndex)
                        if (candidate != null) {
                            scope.launch {
                                viewModel.relabelMotionCaptureSegment(activeReviewSegment.id, candidate)
                            }
                        }
                    },
                    onMarkRest = {
                        scope.launch { viewModel.markMotionCaptureSegmentRest(activeReviewSegment.id) }
                    },
                    onDrop = {
                        scope.launch { viewModel.dropMotionCaptureSegment(activeReviewSegment.id) }
                    },
                    onExport = {
                        scope.launch {
                            val exportPath = viewModel.exportLatestMotionCaptureSession()
                            if (exportPath != null) {
                                Toast.makeText(context, "Exported to $exportPath", Toast.LENGTH_SHORT).show()
                            }
                        }
                    }
                )
            }
        }
    )

    CustomDialogYesOnLongPress(
        show = showNextDialog,
        title =  "Workout complete",
        message = "Return to the main menu?",
        handleYesClick = {
            closeJob?.cancel()
            hapticsViewModel.doGentleVibration()
            viewModel.clearCompletionPushCompleted()
            // Flush any pending sync before navigating away
            scope.launch {
                viewModel.flushWorkoutSync()
            }
            navController.navigate(Screen.WorkoutSelection.route){
                popUpTo(0) {
                    inclusive = true
                }
            }
            viewModel.closeCustomDialog()
        },
        handleNoClick = {
            viewModel.closeCustomDialog()
            hapticsViewModel.doGentleVibration()
            startCloseJob()
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            viewModel.closeCustomDialog()
            startCloseJob()
        },
        onVisibilityChange = { isVisible ->
            if (isVisible) {
                closeJob?.cancel()
                viewModel.setDimming(false)
            } else {
                viewModel.reEvaluateDimmingForCurrentState()
            }
        }
    )
}

@Composable
private fun WorkoutCompleteScreenContent(
    workoutName: String,
    countDownSeconds: Int,
    showCountdown: Boolean = true,
    progressionContent: @Composable ColumnScope.() -> Unit,
    motionReviewContent: @Composable ColumnScope.() -> Unit = {}
) {
    val headerStyle = MaterialTheme.typography.bodyExtraSmall

    Column(
        verticalArrangement = Arrangement.SpaceBetween,
        horizontalAlignment = Alignment.CenterHorizontally,
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 5.dp)
            .padding(
                top = WorkoutPagerHeaderReservedHeight + 2.5.dp,
                bottom = 25.dp
            )
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp)
                .padding(bottom = 5.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(2.5.dp)
        ) {
            Text(
                text = "COMPLETED",
                textAlign = TextAlign.Center,
                style = headerStyle
            )
            ScalableText(
                modifier = Modifier.fillMaxWidth(),
                textModifier = Modifier.fillMaxWidth(),
                text = workoutName,
                style = MaterialTheme.typography.titleLarge
            )
        }

        progressionContent()
        motionReviewContent()
        if(showCountdown){
            Text(
                modifier = Modifier.padding(top = 5.dp),
                text = "CLOSING IN: $countDownSeconds",
                style = headerStyle,
                textAlign = TextAlign.Center,
            )
        }
    }
}

@Composable
private fun ColumnScope.MotionCaptureReviewPanel(
    segment: MotionCaptureSegmentRecord,
    segmentIndex: Int,
    segmentCount: Int,
    candidateNames: List<String>,
    selectedCandidateIndex: Int,
    lastExportDirectory: String?,
    onPreviousSegment: () -> Unit,
    onNextSegment: () -> Unit,
    onNextCandidate: () -> Unit,
    onConfirm: () -> Unit,
    onUseCandidate: () -> Unit,
    onMarkRest: () -> Unit,
    onDrop: () -> Unit,
    onExport: () -> Unit
) {
    val displayedLabel = segment.correctedLabel ?: segment.autoLabel
    val durationSeconds = ((segment.endedAtEpochMs ?: segment.startedAtEpochMs) - segment.startedAtEpochMs) / 1000.0

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 6.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        Text(
            text = "MOTION REVIEW ${segmentIndex + 1}/$segmentCount",
            style = MaterialTheme.typography.bodyExtraSmall,
            textAlign = TextAlign.Center
        )
        Text(
            text = "${displayedLabel.exerciseName ?: displayedLabel.kind.name} • ${"%.1f".format(durationSeconds)}s",
            style = MaterialTheme.typography.bodySmall,
            textAlign = TextAlign.Center
        )
        Text(
            text = "Status: ${segment.reviewStatus.name}",
            style = MaterialTheme.typography.bodyExtraSmall,
            textAlign = TextAlign.Center
        )
        if (candidateNames.isNotEmpty()) {
            Text(
                text = "Candidate: ${candidateNames[selectedCandidateIndex.coerceIn(candidateNames.indices)]}",
                style = MaterialTheme.typography.bodyExtraSmall,
                textAlign = TextAlign.Center
            )
        }
        if (lastExportDirectory != null) {
            Text(
                text = lastExportDirectory,
                style = MaterialTheme.typography.bodyExtraSmall,
                textAlign = TextAlign.Center,
                maxLines = 2
            )
        }
        WearPrimaryButton(
            modifier = Modifier.fillMaxWidth(),
            text = "Confirm",
            onClick = onConfirm
        )
        ButtonWithText(
            modifier = Modifier.fillMaxWidth(),
            text = "Next candidate",
            enabled = candidateNames.isNotEmpty(),
            onClick = onNextCandidate
        )
        ButtonWithText(
            modifier = Modifier.fillMaxWidth(),
            text = "Use candidate",
            enabled = candidateNames.isNotEmpty(),
            onClick = onUseCandidate
        )
        OutlinedButtonWithText(
            modifier = Modifier.fillMaxWidth(),
            text = "Mark rest",
            onClick = onMarkRest
        )
        OutlinedButtonWithText(
            modifier = Modifier.fillMaxWidth(),
            text = "Drop segment",
            onClick = onDrop
        )
        ButtonWithText(
            modifier = Modifier.fillMaxWidth(),
            text = "Export session",
            onClick = onExport
        )
        Spacer(modifier = Modifier.fillMaxWidth())
        ButtonWithText(
            modifier = Modifier.fillMaxWidth(),
            text = "Previous segment",
            enabled = segmentIndex > 0,
            onClick = onPreviousSegment
        )
        ButtonWithText(
            modifier = Modifier.fillMaxWidth(),
            text = "Next segment",
            enabled = segmentIndex < segmentCount - 1,
            onClick = onNextSegment
        )
    }
}

@Preview(device = WearDevices.LARGE_ROUND, showBackground = true)
@Composable
private fun WorkoutCompleteScreenPreview() {
    MaterialTheme(
        colorScheme = darkScheme,
        typography = baseline,
    ) {
        WorkoutCompleteScreenContent(
            workoutName = "Push Day",
            countDownSeconds = 30,
            progressionContent = {
                Text(
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxWidth(),
                    text = "PROGRESS SUMMARY",
                    textAlign = TextAlign.Center,
                    style = MaterialTheme.typography.bodySmall
                )
            }
        )
    }
}
