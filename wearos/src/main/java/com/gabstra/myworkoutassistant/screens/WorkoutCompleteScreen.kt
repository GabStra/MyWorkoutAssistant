package com.gabstra.myworkoutassistant.screens

import android.annotation.SuppressLint
import android.app.Activity
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
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
import androidx.navigation.NavController
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.composables.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.composables.ProgressionSection
import com.gabstra.myworkoutassistant.composables.ScalableText
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.PolarViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.SensorDataViewModel
import com.gabstra.myworkoutassistant.data.cancelWorkoutInProgressNotification
import com.gabstra.myworkoutassistant.data.verticalColumnScrollbar
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.time.Duration

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

    val duration = remember {
        Duration.between(state.startWorkoutTime, state.endWorkoutTime)
    }

    val hours = remember { duration.toHours() }
    val minutes = remember { duration.toMinutes() % 60 }
    val seconds = remember { duration.seconds % 60 }
    val hasWorkoutRecord by viewModel.hasWorkoutRecord.collectAsState()

    val countDownTimer = remember { mutableIntStateOf(30) }

    val typography = MaterialTheme.typography
    val headerStyle = remember(typography) { typography.body1.copy(fontSize = typography.body1.fontSize * 0.625f) }

    val scope = rememberCoroutineScope()
    var closeJob by remember { mutableStateOf<Job?>(null) }

    LaunchedEffect(Unit){
        delay(500)
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

            closeJob = scope.launch {
                while(countDownTimer.intValue > 0){
                    countDownTimer.intValue--
                    delay(1000)
                }

                val activity = (context as? Activity)
                activity?.finishAndRemoveTask()
            }
        }
    }

    val scrollState = rememberScrollState()

    Column(
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
        modifier = Modifier
            .fillMaxSize()
            .padding(30.dp)
            .verticalColumnScrollbar(scrollState)
            .verticalScroll(scrollState)
    ) {
        Column(
            modifier = Modifier.fillMaxWidth(),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(2.5.dp)
        ) {
            Text(
                text = "COMPLETED",
                textAlign = TextAlign.Center,
                style = headerStyle
            )
            ScalableText(
                text = workout.name,
                style = MaterialTheme.typography.title3
            )
            Spacer(modifier = Modifier.height(0.dp))
            Text(
                text = "TIME SPENT",
                textAlign = TextAlign.Center,
                style = headerStyle
            )
            ScalableText(
                text = String.format("%02d:%02d:%02d", hours, minutes, seconds),
                textAlign = TextAlign.Center,
                style =  MaterialTheme.typography.title3
            )
        }
        ProgressionSection(modifier = Modifier.weight(1f).padding(top = 5.dp),viewModel = viewModel)
        Text(
            modifier = Modifier.padding(top = 5.dp),
            text = "CLOSING IN: ${countDownTimer.intValue}",
            style = headerStyle,
            textAlign = TextAlign.Center,
        )
    }

    CustomDialogYesOnLongPress(
        show = showNextDialog,
        title =  "Finish workout",
        message = "Do you want to go back to the main menu?",
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
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            viewModel.closeCustomDialog()
        },
        holdTimeInMillis = 1000,
        onVisibilityChange = { isVisible ->
            if (isVisible) {
                viewModel.setDimming(false)
            } else {
                viewModel.reEvaluateDimmingForCurrentState()
            }
        }
    )
}