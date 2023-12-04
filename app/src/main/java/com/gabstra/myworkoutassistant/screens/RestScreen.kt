package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.combinedClickable
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
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable;
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.CircularProgressIndicator
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myhomeworkoutassistant.data.AppViewModel
import com.gabstra.myhomeworkoutassistant.data.WorkoutState
import com.gabstra.myworkoutassistant.data.FormatTime
import com.gabstra.myworkoutassistant.data.VibrateOnce
import com.gabstra.myworkoutassistant.data.VibrateShortImpulse

import kotlinx.coroutines.delay

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun NextExerciseInfo(
    viewModel: AppViewModel,
    state: WorkoutState.Set
){
    val workout by viewModel.selectedWorkout

    Column(
        modifier = Modifier
            .size(160.dp, 190.dp)
            .padding(top = 75.dp),
        verticalArrangement = Arrangement.Top,
        horizontalAlignment = Alignment.CenterHorizontally,
    ){
        Column(
            verticalArrangement = Arrangement.Top,
            horizontalAlignment = Alignment.CenterHorizontally,
        ){
            Text(
                text = "Coming soon",
                style = MaterialTheme.typography.body2
            )

            /*
            Text(
                text = "Next:",
                style = MaterialTheme.typography.body2
            )
            Spacer(modifier = Modifier.height(5.dp))
            Row(
                horizontalArrangement = Arrangement.Center,
                modifier = Modifier
                    .fillMaxWidth()
            ) {
                Text(
                    text = "Exercise: ${workout.workoutComponents.indexOf(state.workoutComponent)+1}/${workout.workoutComponents.count()}",
                    style = MaterialTheme.typography.body2
                )
                Spacer(modifier = Modifier.width(5.dp))
                Text(
                    text = "Set: ${state.currentSetData}/${state.workoutComponent.sets}",
                    textAlign = TextAlign.Center,
                    style = MaterialTheme.typography.body2,
                )
            }


            Spacer(modifier = Modifier.height(5.dp))
            if(state.workoutComponent.exercises.count() != 1){
                Text(
                    text = "${state.workoutComponent.name}",
                    modifier = Modifier.basicMarquee(),
                    style = MaterialTheme.typography.body2,
                    textAlign = TextAlign.Center,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Spacer(modifier = Modifier.height(5.dp))
            }

            Text(
                text = "${state.exerciseName}",
                modifier = Modifier.basicMarquee(),
                style = MaterialTheme.typography.body2,
                textAlign = TextAlign.Center,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
            Row(
                horizontalArrangement = Arrangement.Center,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 5.dp)
            ) {
                Text(
                    text = "${state.reps} reps",
                    style = MaterialTheme.typography.body2
                )
                if (!bodyWeight) {
                    Spacer(modifier = Modifier.width(5.dp))
                    Text(
                        text = "${state.weight} kg",
                        style = MaterialTheme.typography.body2
                    )
                }
            }
            */
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun RestScreen(
    viewModel: AppViewModel,
    state: WorkoutState.Rest
) {
    val totalSeconds = state.restTimeInSec;
    var currentMillis by remember { mutableIntStateOf(totalSeconds * 1000) }
    val context = LocalContext.current

    LaunchedEffect(key1 = totalSeconds) {
        delay(500)
        while (currentMillis > 0) {
            delay(1000) // Update every 18 milliseconds.
            currentMillis -= 1000
        }

        VibrateShortImpulse(context);
        viewModel.goToNextState()
    }

    val progress = (currentMillis.toFloat() / (totalSeconds * 1000))

    Box(
        modifier = Modifier
            .fillMaxSize()
            .combinedClickable(
                onClick = {},
                onLongClick = {
                    VibrateOnce(context);
                    viewModel.goToNextState()
                }
            ),
        contentAlignment = Alignment.TopCenter
    ) {
        CircularProgressIndicator(
            progress = progress,
            modifier = Modifier.fillMaxSize(),
            startAngle = 290f,
            endAngle = 250f,
            strokeWidth = 4.dp,
            indicatorColor = MaterialTheme.colors.primary
        )

        Box(
            modifier = Modifier.size(160.dp,90.dp).padding(0.dp,30.dp),
            contentAlignment = Alignment.TopCenter
        ){
            Text(
                text = FormatTime(currentMillis / 1000),
                style = MaterialTheme.typography.display3,
            )
        }

        val nextWorkoutState by viewModel.nextWorkoutState
        when(nextWorkoutState){
            is WorkoutState.Set -> {
                val state = nextWorkoutState as WorkoutState.Set
                NextExerciseInfo(viewModel,state)
            }
            else -> {}
        }
    }
}

