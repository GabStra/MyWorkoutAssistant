package com.gabstra.myworkoutassistant.screens

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Context
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

    val hasWorkoutRecord by viewModel.hasWorkoutRecord.collectAsState()
    val countDownTimer = remember { mutableIntStateOf(10) }

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

        viewModel.pushAndStoreWorkoutData(true,context){
            if(hasWorkoutRecord) viewModel.deleteWorkoutRecord()

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
            viewModel = viewModel
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
        holdTimeInMillis = 1000,
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