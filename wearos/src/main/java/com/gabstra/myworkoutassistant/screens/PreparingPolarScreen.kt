package com.gabstra.myworkoutassistant.screens

import android.util.Log
import android.widget.Toast
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.health.services.client.data.ExerciseState
import androidx.navigation.NavController
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myhomeworkoutassistant.data.AppViewModel
import com.gabstra.myhomeworkoutassistant.data.WorkoutState
import com.gabstra.myworkoutassistant.composable.LoadingText
import com.gabstra.myworkoutassistant.data.MeasureDataViewModel
import com.gabstra.myworkoutassistant.data.PolarViewModel
import com.gabstra.myworkoutassistant.data.VibrateShortImpulse
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
@Composable
fun PreparingPolarScreen(
    viewModel: AppViewModel,
    navController: NavController,
    polarViewModel: PolarViewModel,
    state: WorkoutState.Preparing,
){
    val deviceConnectionInfo by polarViewModel.deviceConnectionState.collectAsState()
    val hrData by polarViewModel.hrDataState.collectAsState()

    val heartRate =  hrData?.get(0) ?: 0

    val scope = rememberCoroutineScope()
    var currentMillis by remember { mutableIntStateOf(0) }
    val context = LocalContext.current
    LaunchedEffect(Unit){
        if(viewModel.polarDeviceId == null){
            Toast.makeText(context, "No polar device id set", Toast.LENGTH_SHORT).show()
            navController.popBackStack()
            VibrateShortImpulse(context);
            return@LaunchedEffect
        }

        polarViewModel.connectToDevice()

        scope.launch {
            while (true) {
                delay(1000) // Update every sec.
                currentMillis += 1000
            }
        }
    }

    LaunchedEffect(deviceConnectionInfo, heartRate,state,currentMillis) {
        Log.d("PreparingPolarScreen", "deviceConnectionInfo: $deviceConnectionInfo, heartRate: $heartRate, state: $state, currentMillis: $currentMillis")
        val isReady = (deviceConnectionInfo != null) && (heartRate > 0) && state.dataLoaded && currentMillis >=2000
        if (isReady) {
            viewModel.goToNextState()
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 40.dp),
        contentAlignment = Alignment.Center
    ) {
        Column(){
            Text(text = "Preparing Polar", style = MaterialTheme.typography.body2)
            Spacer(modifier = Modifier.height(10.dp))
            Row(modifier = Modifier.width(180.dp)){
                LoadingText(baseText =  if(deviceConnectionInfo == null) "Connecting" else "Loading HR")
            }
        }
    }
}