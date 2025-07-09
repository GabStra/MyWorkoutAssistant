package com.gabstra.myworkoutassistant.screens

import android.annotation.SuppressLint
import android.app.Activity
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.PolarViewModel
import com.gabstra.myworkoutassistant.data.SensorDataViewModel
import com.gabstra.myworkoutassistant.data.cancelWorkoutInProgressNotification
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
            delay(5000)
            val activity = (context as? Activity)
            activity?.finishAndRemoveTask()
        }
    }

    Column(
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
        modifier = Modifier
            .fillMaxSize()
    ) {
        Text(
            text = "Time spent: ${String.format("%02d:%02d:%02d", hours, minutes, seconds)}",
            style = MaterialTheme.typography.body2,
        )
        Spacer(modifier = Modifier.height(10.dp))
        Text(
            text = workout.name,
            modifier = Modifier.basicMarquee(iterations = Int.MAX_VALUE),
            textAlign = TextAlign.Center,
            style = MaterialTheme.typography.title3
        )
        Text(
            text = "Completed",
            textAlign = TextAlign.Center,
            style = MaterialTheme.typography.body2
        )
    }
}