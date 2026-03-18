package com.gabstra.myworkoutassistant.screens

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Context
import android.widget.Toast
import androidx.compose.foundation.ExperimentalFoundationApi
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
import com.gabstra.myworkoutassistant.composables.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.composables.ProgressionSection
import com.gabstra.myworkoutassistant.composables.ScalableText
import com.gabstra.myworkoutassistant.composables.WorkoutPagerHeaderReservedHeight
import com.gabstra.myworkoutassistant.composables.rememberWearCoroutineScope
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.PolarViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.SensorDataViewModel
import com.gabstra.myworkoutassistant.data.cancelWorkoutInProgressNotification
import com.gabstra.myworkoutassistant.presentation.theme.baseline
import com.gabstra.myworkoutassistant.presentation.theme.darkScheme
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
    polarViewModel: PolarViewModel
){
    val showNextDialog by viewModel.isCustomDialogOpen.collectAsState()
    val workout by viewModel.selectedWorkout
    val context = LocalContext.current

    val countDownTimer = remember { mutableIntStateOf(30) }
    var progressionDataCalculated by remember { mutableStateOf(false) }
    var progressionIsEmpty by remember { mutableStateOf<Boolean?>(null) }
    var completionSyncInitiated by remember { mutableStateOf(false) }

    val scope = rememberWearCoroutineScope()
    var closeJob by remember { mutableStateOf<Job?>(null) }

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

            if (!workout.usePolarDevice) {
                hrViewModel.stopMeasuringHeartRate()
            } else {
                polarViewModel.disconnectFromDevice()
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
    progressionContent: @Composable ColumnScope.() -> Unit
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
