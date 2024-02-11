package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.basicMarquee
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.WorkoutState
import com.gabstra.myworkoutassistant.data.Screen
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Devices
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import androidx.navigation.compose.rememberNavController
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.ButtonDefaults
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import androidx.wear.tooling.preview.devices.WearDevices
import com.gabstra.myworkoutassistant.composable.LoadingText
import com.google.android.gms.wearable.DataClient

import java.time.Duration
import java.time.LocalDateTime

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun WorkoutCompleteScreen(navController: NavController, viewModel: AppViewModel, state : WorkoutState.Finished){
    val workout by viewModel.selectedWorkout

    val duration = remember {
        Duration.between(state.startWorkoutTime, LocalDateTime.now())
    }

    val hours = remember { duration.toHours() }
    val minutes = remember { duration.toMinutes() % 60 }
    val seconds = remember { duration.seconds % 60 }

    var hideAll by remember { mutableStateOf(false) }

    var isClickable by remember { mutableStateOf(true) }

    Column(
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
        modifier = Modifier
            .fillMaxSize()
    ) {
        if(!hideAll){
            Text(
                text = "Time spent: ${String.format("%02d:%02d:%02d", hours, minutes, seconds)}",
                style = MaterialTheme.typography.body2,
            )

            Spacer(modifier = Modifier.height(10.dp))
            Text(
                text = workout.name,
                modifier = Modifier.basicMarquee(),
                textAlign = TextAlign.Center,
                style = MaterialTheme.typography.title3
            )
            Text(
                text = "Completed",
                textAlign = TextAlign.Center,
                style = MaterialTheme.typography.body2
            )

            Spacer(modifier = Modifier.height(25.dp))
            Button(
                onClick = {
                    isClickable = false;
                    hideAll=true
                    viewModel.endWorkout(duration){
                        navController.navigate(Screen.WorkoutSelection.route){
                            popUpTo(Screen.WorkoutSelection.route) {
                                inclusive = true
                            }
                        }
                    }
                },
                enabled = isClickable,
                modifier = Modifier.size(35.dp),
                colors = ButtonDefaults.buttonColors(backgroundColor = MaterialTheme.colors.primary)
            ) {
                Icon(imageVector = Icons.Default.Check, contentDescription = "Done")
            }
        }else{
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 40.dp),
                contentAlignment = Alignment.BottomCenter
            ) {
                LoadingText("Saving data")
            }
        }
    }
}

@Preview(device = WearDevices.LARGE_ROUND)
@Composable
fun WorkoutCompleteScreenPreview() {
    val mockNavController = rememberNavController()
    val mockViewModel = AppViewModel() // Assuming you have a default constructor, otherwise create a mock
    val mockState = WorkoutState.Finished(LocalDateTime.now().minusHours(1)) // Example start time

    WorkoutCompleteScreen(mockNavController, mockViewModel, mockState)
}