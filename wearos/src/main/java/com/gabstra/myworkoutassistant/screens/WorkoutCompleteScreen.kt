package com.gabstra.myworkoutassistant.screens

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Context
import android.widget.Toast
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
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
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.content.edit
import androidx.navigation.NavController
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.composables.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.composables.ProgressionSection
import com.gabstra.myworkoutassistant.composables.ScalableText
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.PolarViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.SensorDataViewModel
import com.gabstra.myworkoutassistant.data.cancelWorkoutInProgressNotification
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import java.time.Duration
import java.time.LocalDateTime
import java.time.temporal.ChronoUnit

private const val TAG = "WorkoutCompleteScreen"

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
    var syncComplete by remember { mutableStateOf(false) }
    var completionSyncInitiated by remember { mutableStateOf(false) }

    val headerStyle = MaterialTheme.typography.bodySmall

    val scope = rememberCoroutineScope()
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
                Toast.makeText(context, "Workout saved. Closing app.", Toast.LENGTH_SHORT).show()
                (context as? Activity)?.finishAndRemoveTask()
            }
        }
    }

    LaunchedEffect(Unit){
        delay(500)

        val prefs = context.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
        prefs.edit { putBoolean("isWorkoutInProgress", false) }

        viewModel.setDimming(false)
        hapticsViewModel.doShortImpulse()
        if(!workout.usePolarDevice){
            hrViewModel.stopMeasuringHeartRate()
        }else{
            polarViewModel.disconnectFromDevice()
        }
        cancelWorkoutInProgressNotification(context)

        // Ensure final workout history is stored with isDone=true and scheduled for sync.
        // Guard against duplicate execution if LaunchedEffect runs multiple times
        if (!completionSyncInitiated) {
            completionSyncInitiated = true
            viewModel.pushAndStoreWorkoutData(isDone = true, context = context, forceNotSend = false) {
                android.util.Log.d(
                    "WorkoutSync",
                    "SYNC_TRACE event=completion_force_send side=wear isDone=true"
                )
                viewModel.flushWorkoutSync()
            }
        }

        // Wait for sync to start and complete
        // First, wait for sync status to become Syncing (with timeout)
        val syncStarted = withTimeoutOrNull(5_000) {
            viewModel.syncStatus
                .first { it == AppViewModel.SyncStatus.Syncing }
        }
        
        if (syncStarted != null) {
            // Sync started, now wait for it to complete (Success or Failure)
            val completedStatus = withTimeoutOrNull(30_000) {
                viewModel.syncStatus
                    .first { it == AppViewModel.SyncStatus.Success || it == AppViewModel.SyncStatus.Failure }
            }
            // Only mark as complete if we got a confirmed completion status
            if (completedStatus != null) {
                syncComplete = true
            } else {
                // Sync started but didn't complete within timeout
                // Check current status - if it's Success/Failure, we're done
                // Otherwise, sync may have timed out or failed silently
                val finalStatus = viewModel.syncStatus.value
                if (finalStatus == AppViewModel.SyncStatus.Success || finalStatus == AppViewModel.SyncStatus.Failure) {
                    syncComplete = true
                } else {
                    // Sync started but didn't complete - wait a bit more and check again
                    delay(1_000)
                    val checkStatus = viewModel.syncStatus.value
                    if (checkStatus == AppViewModel.SyncStatus.Success || checkStatus == AppViewModel.SyncStatus.Failure) {
                        syncComplete = true
                    } else {
                        // Sync didn't complete, but proceed anyway to avoid blocking UI indefinitely
                        android.util.Log.w(
                            TAG,
                            "Sync started but did not complete within timeout. Current status: $checkStatus"
                        )
                        syncComplete = true
                    }
                }
            }
        } else {
            // Sync didn't start within timeout - check if it's already done or won't happen
            val currentStatus = viewModel.syncStatus.value
            when (currentStatus) {
                AppViewModel.SyncStatus.Success, AppViewModel.SyncStatus.Failure -> {
                    // Sync already completed (from a previous sync or completed very quickly)
                    syncComplete = true
                }
                AppViewModel.SyncStatus.Idle -> {
                    // Check if there's a pending sync that might start
                    if (viewModel.hasPendingWorkoutSync.value) {
                        // Wait a bit more for pending sync to start
                        val pendingSyncStatus = withTimeoutOrNull(3_000) {
                            while (viewModel.hasPendingWorkoutSync.value &&
                                viewModel.syncStatus.value == AppViewModel.SyncStatus.Idle
                            ) {
                                delay(200)
                            }
                            viewModel.syncStatus.value
                        }
                        
                        if (pendingSyncStatus == AppViewModel.SyncStatus.Syncing) {
                            // Pending sync started, wait for completion
                            val completedStatus = withTimeoutOrNull(30_000) {
                                viewModel.syncStatus
                                    .first { it == AppViewModel.SyncStatus.Success || it == AppViewModel.SyncStatus.Failure }
                            }
                            if (completedStatus != null) {
                                syncComplete = true
                            } else {
                                // Check final status
                                val finalStatus = viewModel.syncStatus.value
                                syncComplete = (finalStatus == AppViewModel.SyncStatus.Success || finalStatus == AppViewModel.SyncStatus.Failure)
                            }
                        } else if (pendingSyncStatus == AppViewModel.SyncStatus.Success || pendingSyncStatus == AppViewModel.SyncStatus.Failure) {
                            // Sync completed very quickly
                            syncComplete = true
                        } else {
                            // No sync will happen (no connection, etc.) - proceed
                            syncComplete = true
                        }
                    } else {
                        // No sync pending and status is Idle - no sync will happen, proceed
                        syncComplete = true
                    }
                }
                AppViewModel.SyncStatus.Syncing -> {
                    // Sync is in progress (started between checks), wait for completion
                    val completedStatus = withTimeoutOrNull(30_000) {
                        viewModel.syncStatus
                            .first { it == AppViewModel.SyncStatus.Success || it == AppViewModel.SyncStatus.Failure }
                    }
                    syncComplete = (completedStatus != null || 
                        viewModel.syncStatus.value == AppViewModel.SyncStatus.Success ||
                        viewModel.syncStatus.value == AppViewModel.SyncStatus.Failure)
                }
            }
        }

        // Clean up the workout record on the watch after final sync attempt.
        viewModel.deleteWorkoutRecord()
    }

    // Start countdown when both progression is calculated and sync is complete
    LaunchedEffect(progressionDataCalculated, syncComplete) {
        if (progressionDataCalculated && syncComplete && progressionIsEmpty != null) {
            // Set timer duration: 5 seconds if empty/null, 30 seconds if has data
            val timerDuration = if (progressionIsEmpty == true) 5 else 30
            countDownTimer.intValue = timerDuration
            startCloseJob()
        }
    }

    Column(
        verticalArrangement = Arrangement.spacedBy(5.dp, Alignment.CenterVertically),
        horizontalAlignment = Alignment.CenterHorizontally,
        modifier = Modifier
            .fillMaxSize()
            .padding(30.dp)
    ) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(bottom = 2.5.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(2.5.dp)
        ) {
            Text(
                text = "Completed",
                textAlign = TextAlign.Center,
                style = headerStyle
            )
            ScalableText(
                text = workout.name,
                style = MaterialTheme.typography.titleLarge
            )
        }
        ProgressionSection(
            modifier = Modifier.weight(1f),
            viewModel = viewModel,
            onProgressionDataCalculated = { isEmpty ->
                if (!progressionDataCalculated) {
                    progressionDataCalculated = true
                    progressionIsEmpty = isEmpty
                }
            }
        )
        if (syncComplete) {
            Text(
                modifier = Modifier.padding(top = 2.5.dp),
                text = "Closing in: ${countDownTimer.intValue}",
                style = headerStyle,
                textAlign = TextAlign.Center,
            )
        }
    }

    CustomDialogYesOnLongPress(
        show = showNextDialog,
        title =  "Workout completed",
        message = "Return to the main menu?",
        handleYesClick = {
            closeJob?.cancel()
            hapticsViewModel.doGentleVibration()
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
