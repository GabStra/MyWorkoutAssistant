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
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.composables.ProgressionSection
import com.gabstra.myworkoutassistant.composables.ScalableText
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.PolarViewModel
import com.gabstra.myworkoutassistant.data.SensorDataViewModel
import com.gabstra.myworkoutassistant.data.cancelWorkoutInProgressNotification
import com.gabstra.myworkoutassistant.data.verticalColumnScrollbar
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import kotlinx.coroutines.delay
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

    LaunchedEffect(Unit){
        delay(500)
        hapticsViewModel.doShortImpulse()
        if(!workout.usePolarDevice){
            hrViewModel.stopMeasuringHeartRate()
        }else{
            polarViewModel.disconnectFromDevice()
        }
        cancelWorkoutInProgressNotification(context)

        viewModel.pushAndStoreWorkoutData(true,context){
            if(hasWorkoutRecord) viewModel.deleteWorkoutRecord()

            while(countDownTimer.intValue > 0){
                countDownTimer.intValue--
                delay(1000)
            }

            val activity = (context as? Activity)
            activity?.finishAndRemoveTask()
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
            modifier = Modifier.fillMaxWidth().weight(1f),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                text = "COMPLETED",
                textAlign = TextAlign.Center,
                style = headerStyle
            )
            Spacer(modifier = Modifier.height(2.5.dp))
            ScalableText(
                text = workout.name,
                style = MaterialTheme.typography.title3
            )
            Spacer(modifier = Modifier.height(5.dp))
            Text(
                text = "TIME SPENT",
                textAlign = TextAlign.Center,
                style = headerStyle
            )
            Spacer(modifier = Modifier.height(2.5.dp))
            ScalableText(
                text = String.format("%02d:%02d:%02d", hours, minutes, seconds),
                textAlign = TextAlign.Center,
                style =  MaterialTheme.typography.title3
            )
            Spacer(modifier = Modifier.height(5.dp))
            ProgressionSection(modifier = Modifier.weight(1f),viewModel = viewModel)
            Spacer(modifier = Modifier.height(5.dp))
            Text(
                text = "CLOSING IN: ${countDownTimer.intValue}",
                style = headerStyle,
                textAlign = TextAlign.Center,
            )
        }
    }
}