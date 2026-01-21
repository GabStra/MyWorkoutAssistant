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

    val hasWorkoutRecord by viewModel.hasWorkoutRecord.collectAsState()
    val countDownTimer = remember { mutableIntStateOf(30) }
    var progressionDataCalculated by remember { mutableStateOf(false) }
    var progressionIsEmpty by remember { mutableStateOf<Boolean?>(null) }
    var syncComplete by remember { mutableStateOf(false) }

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

        // Capture initial sync status before flush
        val initialStatus = viewModel.syncStatus.value

        // Flush any pending debounced sync to ensure the final workout state (with isDone=true)
        // is synced immediately, preventing cancellation if the app closes or navigates away.
        viewModel.flushWorkoutSync()

        // Small delay to allow sync action to start and set status to Syncing
        delay(200)

        // Check syncStatus after delay
        val currentStatus = viewModel.syncStatus.value
        when (currentStatus) {
            AppViewModel.SyncStatus.Syncing -> {
                // A sync was pending and started, wait for it to complete
                val completedStatus = withTimeoutOrNull(30_000) {
                    viewModel.syncStatus
                        .first { it == AppViewModel.SyncStatus.Success || it == AppViewModel.SyncStatus.Failure }
                }
                // Set syncComplete regardless of timeout - proceed even if sync takes too long
                syncComplete = true
            }
            AppViewModel.SyncStatus.Idle -> {
                if (viewModel.hasPendingWorkoutSync.value) {
                    // Wait briefly for pending sync to start or clear
                    withTimeoutOrNull(30_000) {
                        while (viewModel.hasPendingWorkoutSync.value &&
                            viewModel.syncStatus.value == AppViewModel.SyncStatus.Idle
                        ) {
                            delay(200)
                        }
                    }
                }
                // No sync was pending or it did not start in time
                syncComplete = true
            }
            AppViewModel.SyncStatus.Success, AppViewModel.SyncStatus.Failure -> {
                // Sync already completed (from a previous sync)
                syncComplete = true
            }
        }

        // The last set completion already synced the workout history with isDone=true to mobile.
        // We just need to clean up the workout record on the watch.
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
        Text(
            modifier = Modifier.padding(top = 2.5.dp),
            text = "Closing in: ${countDownTimer.intValue}",
            style = headerStyle,
            textAlign = TextAlign.Center,
        )
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
