package com.gabstra.myworkoutassistant.screens

import com.gabstra.myhomeworkoutassistant.data.AppViewModel
import com.gabstra.myhomeworkoutassistant.data.WorkoutState
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
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.ButtonDefaults
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.google.android.gms.wearable.DataClient

import java.time.Duration
import java.time.LocalDateTime

@Composable
fun WorkoutCompleteScreen(dataClient: DataClient, navController: NavController, viewModel: AppViewModel, state : WorkoutState.Finished){
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
                text = "${workout.name}",
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
                    viewModel.endWorkout(dataClient){
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
                Text(
                    text = "Saving data...",
                    textAlign = TextAlign.Center,
                    style = MaterialTheme.typography.title3
                )
            }
        }
    }
}