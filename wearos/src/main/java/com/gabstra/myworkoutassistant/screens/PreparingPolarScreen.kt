package com.gabstra.myworkoutassistant.screens

import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DoubleArrow
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
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.ButtonDefaults
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.composables.LoadingText
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.PolarViewModel
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@Composable
fun PreparingPolarScreen(
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    navController: NavController,
    polarViewModel: PolarViewModel,
    state: WorkoutState.Preparing,
    onReady: () -> Unit = {}
) {
    BackHandler(true) {
        // Do nothing
    }

    val deviceConnectionInfo by polarViewModel.deviceConnectionState.collectAsState()

    val scope = rememberCoroutineScope()
    var currentMillis by remember { mutableIntStateOf(0) }
    var canSkip by remember { mutableStateOf(false) }
    val context = LocalContext.current
    val hasWorkoutRecord by viewModel.hasWorkoutRecord.collectAsState()
    var hasTriggeredNextState by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        if (viewModel.polarDeviceId.isEmpty()) {
            Toast.makeText(context, "No polar device id set", Toast.LENGTH_SHORT).show()
            navController.popBackStack()
            hapticsViewModel.doShortImpulse()
            return@LaunchedEffect
        }

        polarViewModel.initialize(context, viewModel.polarDeviceId)
        polarViewModel.connectToDevice()

        scope.launch {
            while (true) {
                delay(1000) // Update every sec.
                currentMillis += 1000
                if (currentMillis >= 5000 && !hasTriggeredNextState) {
                    canSkip = true
                    break
                }
            }
        }
    }

    LaunchedEffect(deviceConnectionInfo, state.dataLoaded, currentMillis, hasWorkoutRecord) {
        if (hasTriggeredNextState) {
            return@LaunchedEffect
        }

        val isReady = (deviceConnectionInfo != null) && state.dataLoaded && currentMillis >= 3000
        if (isReady) {
            hasTriggeredNextState = true

            viewModel.lightScreenUp()
            if (hasWorkoutRecord) {
                viewModel.resumeLastState()
            } else {
                viewModel.goToNextState()
                viewModel.setWorkoutStart()
            }

            onReady()
        }
    }

    Box(
        modifier = Modifier.fillMaxSize(),
        contentAlignment = Alignment.CenterStart
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(
                modifier = Modifier.fillMaxWidth(),
                text = "Preparing\nPolar Sensor",
                style = MaterialTheme.typography.caption1,
                textAlign = TextAlign.Center
            )
            Spacer(modifier = Modifier.height(15.dp))
            Row (modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center){
                LoadingText(baseText = "Connecting")
            }


            AnimatedVisibility(
                visible = canSkip && deviceConnectionInfo == null && state.dataLoaded,
                enter = fadeIn(animationSpec = tween(500)),
                exit = fadeOut(animationSpec = tween(500))
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Spacer(modifier = Modifier.height(25.dp))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.Center
                    ) {
                        Button(
                            onClick = {
                                hapticsViewModel.doGentleVibration()
                                viewModel.goToNextState()
                                viewModel.lightScreenUp()
                                viewModel.setWorkoutStart()
                                onReady()
                            },
                            modifier = Modifier.size(35.dp),
                            colors = ButtonDefaults.buttonColors(backgroundColor = MaterialTheme.colors.background)
                        ) {
                            Icon(
                                imageVector = Icons.Default.DoubleArrow,
                                contentDescription = "skip"
                            )
                        }
                    }
                }
            }
        }
    }
}