package com.gabstra.myworkoutassistant.composable

import android.annotation.SuppressLint
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.VibrateGentle
import com.gabstra.myworkoutassistant.data.WorkoutState
import kotlinx.coroutines.delay
import java.time.Duration
import java.time.LocalDateTime
import java.time.temporal.ChronoUnit

@SuppressLint("DefaultLocale")
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun WorkoutStateHeader(
    workoutState: WorkoutState,
    viewModel: AppViewModel
){
    val displayMode by viewModel.headerDisplayMode
    var duration by remember { mutableStateOf(Duration.ZERO) }
    val context = LocalContext.current

    if(displayMode == 1){
        LaunchedEffect(Unit) {
            while (true) {
                val now = LocalDateTime.now()
                duration = Duration.between(viewModel.startWorkoutTime,now)
                val nextSecond = now.plusSeconds(1).truncatedTo(ChronoUnit.SECONDS)
                delay(Duration.between(now, nextSecond).toMillis())
            }
        }
    }

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(20.dp)
            .padding(55.dp,5.dp,55.dp,0.dp)
            .clickable {
                if(workoutState is WorkoutState.Preparing) return@clickable
                viewModel.switchHeaderDisplayMode()
                VibrateGentle(context)
            }
        ,
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.Center
    ) {
        if(displayMode == 0){
            if(workoutState is WorkoutState.Set){
                CurrentExercise(viewModel,workoutState as WorkoutState.Set)
                Spacer(modifier = Modifier.width(5.dp))
                CurrentTime()
            }else{
                CurrentBattery()
                Spacer(modifier = Modifier.width(5.dp))
                CurrentTime()
            }
        }else{
            val hours = remember(duration) { duration.toHours() }
            val minutes = remember(duration) { duration.toMinutes() % 60 }
            val seconds = remember(duration) { duration.seconds % 60 }

            Text(
                textAlign = TextAlign.Center,
                text = String.format("%02d:%02d:%02d", hours, minutes, seconds),
                style = MaterialTheme.typography.caption1
            )
        }

    }
}