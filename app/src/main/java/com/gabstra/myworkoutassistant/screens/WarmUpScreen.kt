package com.gabstra.myworkoutassistant.screens


import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.wear.compose.material.Text
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
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
import androidx.compose.ui.unit.dp
import androidx.health.services.client.data.ExerciseState
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.ButtonDefaults
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.MaterialTheme
import com.gabstra.myhomeworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.composable.HeartRateCircularChart
import com.gabstra.myworkoutassistant.data.FormatTime
import com.gabstra.myworkoutassistant.data.GetMHRPercentage
import com.gabstra.myworkoutassistant.data.MeasureDataViewModel
import com.gabstra.myworkoutassistant.data.VibrateOnce
import kotlinx.coroutines.delay

@Composable
fun WarmUpScreen(viewModel: AppViewModel,hrViewModel: MeasureDataViewModel){
    var currentMillis by remember { mutableStateOf(0) }
    var hasWarmupStarted by remember { mutableStateOf(false) }
    val context = LocalContext.current

    LaunchedEffect(key1 = hasWarmupStarted) {
        while (hasWarmupStarted) {
            delay(1000) // Update every 18 milliseconds.
            currentMillis += 1000
        }
    }

    val uiState by hrViewModel.exerciseServiceState.collectAsState();
    val hr = remember(uiState.exerciseState,uiState.exerciseMetrics.heartRate) {
        if(uiState.exerciseState == ExerciseState.ACTIVE) uiState.exerciseMetrics.heartRate ?: 0 else 0
    }

    val mhrPercentage =  remember(hr) { GetMHRPercentage(hr.toFloat(),28) }
    val mhrText= remember(mhrPercentage) {
        if(mhrPercentage == 0f) "-"
        else "${mhrPercentage.toInt()}%"
    }
    Box(
        modifier = Modifier
            .fillMaxSize()
            .clickable {
                if (!hasWarmupStarted){
                    hasWarmupStarted = true
                    VibrateOnce(context)
                }
            },
        contentAlignment = Alignment.Center
    ) {
        HeartRateCircularChart(
            modifier = Modifier.fillMaxSize(),
            hrViewModel
        )

        Column(
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier.fillMaxSize()
        ){
            Text(
                text = "Warm up",
                style = MaterialTheme.typography.title3,
            )
            Spacer(modifier = Modifier.height(10.dp))

            if(!hasWarmupStarted){
                Text(
                    text = "Press to start",
                    style = MaterialTheme.typography.body2,
                )
            }else{
                Text(
                    text = FormatTime(currentMillis / 1000),
                    style = MaterialTheme.typography.display2,
                )
                Spacer(modifier = Modifier.height(5.dp))
                /*
                Text(
                    text = "$mhrText",
                    style = MaterialTheme.typography.body2,
                )
               Text(
                    text = " (aim for 50% to 70%)",
                    style = MaterialTheme.typography.caption2,
                )
                */
                Spacer(modifier = Modifier.height(10.dp))
                Button(
                    onClick = {
                        VibrateOnce(context)
                        viewModel.goToNextState()
                    },
                    modifier = Modifier.size(35.dp),
                    colors = ButtonDefaults.buttonColors(backgroundColor = MaterialTheme.colors.primary)
                ) {
                    Icon(imageVector = Icons.Default.Check, contentDescription = "Done")
                }
            }
        }
    }
}