package com.gabstra.myworkoutassistant.composable

import android.annotation.SuppressLint
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.presentation.theme.MyColors
import com.gabstra.myworkoutassistant.shared.VibrateGentle
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
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

    val interactionSource = remember { MutableInteractionSource() }

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(20.dp)
            .padding(top = 5.dp)
            .clickable(
                interactionSource = interactionSource,
                indication = null
            ) {
                if(workoutState is WorkoutState.Preparing) return@clickable
                viewModel.switchHeaderDisplayMode()
                VibrateGentle(context)
            }
        ,
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.Center
    ) {
        if(displayMode == 0){
            Row{
                CurrentBattery()
                Spacer(modifier = Modifier.width(5.dp))
                CurrentTime()
            }
        }else{
            val hours = remember(duration) { duration.toHours() }
            val minutes = remember(duration) { duration.toMinutes() % 60 }
            val seconds = remember(duration) { duration.seconds % 60 }

            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(1.dp)
            ) {
                Text(
                    modifier = Modifier.fillMaxHeight(),
                    text = String.format("%02d", hours),
                    style = MaterialTheme.typography.caption1,
                    textAlign = TextAlign.Center
                )

                Text(
                    text = ":",
                    style = MaterialTheme.typography.caption1,

                    textAlign = TextAlign.Center,
                    modifier = Modifier.fillMaxHeight(),
                )

                Text(
                    modifier = Modifier.fillMaxHeight(),
                    text = String.format("%02d", minutes),
                    style = MaterialTheme.typography.caption1,
                    textAlign = TextAlign.Center
                )

                Text(
                    text = ":",
                    style = MaterialTheme.typography.caption1,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.fillMaxHeight(),
                )

                Text(
                    modifier = Modifier.fillMaxHeight(),
                    text = String.format("%02d", seconds),
                    style = MaterialTheme.typography.caption1,
                    textAlign = TextAlign.Center
                )
            }
        }

    }
}