package com.gabstra.myworkoutassistant.composables

import android.annotation.SuppressLint
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AccessTimeFilled
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
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
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
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel
){
    val displayMode by viewModel.headerDisplayMode
    var duration by remember { mutableStateOf(Duration.ZERO) }
    val context = LocalContext.current

    if(displayMode == 1 && viewModel.startWorkoutTime != null){
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

            .padding(top = 10.dp)
            .height(20.dp)
            .clickable(
                interactionSource = interactionSource,
                indication = null
            ) {
                if(workoutState is WorkoutState.Preparing) return@clickable
                viewModel.switchHeaderDisplayMode()
                hapticsViewModel.doGentleVibration()
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
                modifier = Modifier.fillMaxHeight(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(1.dp)
            ) {
                Icon(
                    modifier = Modifier.size(15.dp),
                    imageVector = Icons.Filled.AccessTimeFilled,
                    contentDescription = "clock",
                )
                Spacer(modifier = Modifier.width(2.dp))
                Text(
                    text = String.format("%02d", hours),
                    style = MaterialTheme.typography.caption1,
                    textAlign = TextAlign.Center
                )

                Text(
                    text = ":",
                    style = MaterialTheme.typography.caption1,
                    textAlign = TextAlign.Center,
                )

                Text(
                    text = String.format("%02d", minutes),
                    style = MaterialTheme.typography.caption1,
                    textAlign = TextAlign.Center
                )

                Text(
                    text = ":",
                    style = MaterialTheme.typography.caption1,
                    textAlign = TextAlign.Center,
                )

                Text(
                    text = String.format("%02d", seconds),
                    style = MaterialTheme.typography.caption1,
                    textAlign = TextAlign.Center
                )
            }
        }

    }
}