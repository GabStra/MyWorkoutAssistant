package com.gabstra.myworkoutassistant.screens

import android.annotation.SuppressLint
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.basicMarquee
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import com.gabstra.myworkoutassistant.data.Screen
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.SensorDataViewModel
import com.gabstra.myworkoutassistant.data.PolarViewModel
import com.gabstra.myworkoutassistant.data.VibrateShortImpulse
import com.gabstra.myworkoutassistant.data.VibrateTwice
import com.gabstra.myworkoutassistant.data.VibrateTwiceAndBeep
import com.gabstra.myworkoutassistant.data.cancelWorkoutInProgressNotification
import kotlinx.coroutines.delay

import java.time.Duration
import java.time.LocalDateTime

@SuppressLint("DefaultLocale")
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun WorkoutCompleteScreen(
    navController: NavController,
    viewModel: AppViewModel,
    state : WorkoutState.Finished,
    hrViewModel: SensorDataViewModel,
    polarViewModel: PolarViewModel
){
    val workout by viewModel.selectedWorkout
    val context = LocalContext.current

    val duration = remember {
        Duration.between(state.startWorkoutTime, LocalDateTime.now())
    }

    val hours = remember { duration.toHours() }
    val minutes = remember { duration.toMinutes() % 60 }
    val seconds = remember { duration.seconds % 60 }
    val hasWorkoutRecord by viewModel.hasWorkoutRecord.collectAsState()

    var dataSent by remember { mutableStateOf(false) }

    LaunchedEffect(Unit){
        if(!workout.usePolarDevice){
            hrViewModel.stopMeasuringHeartRate()
        }else{
            polarViewModel.disconnectFromDevice()
        }
        delay(1000)
        cancelWorkoutInProgressNotification(context)
        viewModel.pushAndStoreWorkoutData(true,context){
            dataSent = true
            if(hasWorkoutRecord) viewModel.deleteWorkoutRecord()
        }
    }

    LaunchedEffect(dataSent) {
        if(!dataSent) return@LaunchedEffect
        delay(1000)
        navController.navigate(Screen.WorkoutSelection.route){
            popUpTo(Screen.WorkoutSelection.route) {
                inclusive = true
            }
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