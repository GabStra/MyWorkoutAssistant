package com.gabstra.myworkoutassistant.screens

import android.util.Log
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.ButtonDefaults
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.composable.LoadingText
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.WorkoutState
import com.gabstra.myworkoutassistant.data.SensorDataViewModel
import com.gabstra.myworkoutassistant.data.VibrateGentle
import com.gabstra.myworkoutassistant.data.showWorkoutInProgressNotification
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun PreparingStandardScreen(
    viewModel: AppViewModel,
    hrViewModel: SensorDataViewModel,
    state: WorkoutState.Preparing,
    onReady: () -> Unit = {}
){
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var currentMillis by remember { mutableIntStateOf(0) }
    var canSkip by remember { mutableStateOf(false) }
    val hasWorkoutRecord by viewModel.hasWorkoutRecord.collectAsState()
    var hasTriggeredNextState by remember { mutableStateOf(false) }

    LaunchedEffect(Unit){
        scope.launch {
            while (true) {
                delay(1000) // Update every sec.
                currentMillis += 1000
                if(currentMillis >= 5000){
                    canSkip = true
                    break
                }
            }
        }
    }

    LaunchedEffect(state,currentMillis,hasWorkoutRecord) {
        if(hasTriggeredNextState){
            return@LaunchedEffect
        }

        val isReady = state.dataLoaded && currentMillis >=3000

        if (isReady) {
            hasTriggeredNextState = true

            if(hasWorkoutRecord){
                viewModel.resumeLastState()
            }else{
                viewModel.goToNextState()
                viewModel.setWorkoutStart()
            }

            viewModel.lightScreenUp()
            onReady()
        }
    }

    Box(
        modifier = Modifier.fillMaxSize(),
        contentAlignment = Alignment.Center
    ){
        Column(horizontalAlignment = Alignment.CenterHorizontally){
            Text(modifier = Modifier.fillMaxWidth(), text = "Preparing\nWatch HR Sensor", style = MaterialTheme.typography.body2, textAlign = TextAlign.Center)
            Spacer(modifier = Modifier.height(15.dp))
            LoadingText(baseText = "Please wait")
            if(canSkip && state.dataLoaded){
                Spacer(modifier = Modifier.height(25.dp))
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center){
                    Button(
                        onClick = {
                            VibrateGentle(context)
                            viewModel.goToNextState()
                            viewModel.lightScreenUp()
                            viewModel.setWorkoutStart()
                            onReady()
                        },
                        modifier = Modifier.size(35.dp),
                        colors = ButtonDefaults.buttonColors(backgroundColor = Color.Gray)
                    ) {
                        Icon(imageVector = Icons.Default.DoubleArrow, contentDescription = "skip")
                    }
                }
            }
        }
    }
}