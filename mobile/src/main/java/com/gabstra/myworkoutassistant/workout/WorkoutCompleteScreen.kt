package com.gabstra.myworkoutassistant.workout

import android.annotation.SuppressLint
import android.content.Context
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
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
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.HapticsViewModel
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.time.Duration

@SuppressLint("DefaultLocale")
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun WorkoutCompleteScreen(
    appViewModel: AppViewModel,
    viewModel: WorkoutViewModel,
    state : WorkoutState.Completed,
    hapticsViewModel: HapticsViewModel,
){
    val showNextDialog by viewModel.isCustomDialogOpen.collectAsState()
    val workout by viewModel.selectedWorkout
    val context = LocalContext.current

    val duration = remember {
        Duration.between(state.startWorkoutTime, state.endWorkoutTime)
    }

    val hasWorkoutRecord by viewModel.hasWorkoutRecord.collectAsState()

    val countDownTimer = remember { mutableIntStateOf(15) }

    val headerStyle = MaterialTheme.typography.titleSmall

    val scope = rememberCoroutineScope()
    var closeJob by remember { mutableStateOf<Job?>(null) }

    fun startCloseJob() {
        closeJob?.cancel()
        closeJob = scope.launch {
            var remaining = countDownTimer.intValue

            // schedule first tick on the next second boundary
            var nextExecutionTime = System.currentTimeMillis() + 1000
            nextExecutionTime = (nextExecutionTime / 1000) * 1000

            while (remaining > 0 && isActive) {
                val waitTime = maxOf(0, nextExecutionTime - System.currentTimeMillis())
                delay(waitTime)

                remaining--
                countDownTimer.intValue = remaining

                nextExecutionTime += 1000
            }

            appViewModel.initScreenData(ScreenData.Workouts(0))
        }
    }

    LaunchedEffect(Unit){
        delay(500)

        val prefs = context.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
        prefs.edit { putBoolean("isWorkoutInProgress", false) }

        viewModel.setDimming(false)
        hapticsViewModel.doShortImpulse()

        viewModel.pushAndStoreWorkoutData(true,context){
            if(hasWorkoutRecord) viewModel.deleteWorkoutRecord()

            startCloseJob()
        }
    }

    Column(
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
        modifier = Modifier
            .fillMaxSize()
            .padding(30.dp)
    ) {
        Column(
            modifier = Modifier.fillMaxWidth(),
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
                style = MaterialTheme.typography.displayLarge
            )
        }

        Text(
            modifier = Modifier.padding(top = 5.dp),
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
            appViewModel.goBack()
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

