package com.gabstra.myworkoutassistant.composables

import android.R.attr.digits
import android.annotation.SuppressLint
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
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
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.Icon
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
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
            .padding(top = 7.5.dp)
            .clickable(
                interactionSource = interactionSource,
                indication = null
            ) {
                if(workoutState is WorkoutState.Preparing) return@clickable
                viewModel.switchHeaderDisplayMode()
                hapticsViewModel.doGentleVibration()
            },
        horizontalArrangement = Arrangement.Center
    ) {
        if(displayMode == 0){
            Row(verticalAlignment = Alignment.CenterVertically){
                CurrentBattery()
                Spacer(modifier = Modifier.width(5.dp))
                CurrentTime()
            }
        }else{
            val measurer = rememberTextMeasurer()
            val density = LocalDensity.current
            val captionStyle = MaterialTheme.typography.bodySmall
            val twoDigitWidth = remember(digits, density) {
                with(density) { measurer.measure("00", style =captionStyle).size.width.toDp() }
            }

            val hours = remember(duration) { duration.toHours() }
            val minutes = remember(duration) { duration.toMinutes() % 60 }
            val seconds = remember(duration) { duration.seconds % 60 }

            Row(
                horizontalArrangement = Arrangement.spacedBy(1.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Icon(
                    modifier = Modifier.size(12.5.dp),
                    imageVector = Icons.Filled.AccessTimeFilled,
                    contentDescription = "clock",
                )
                Spacer(modifier = Modifier.width(2.dp))
                Text(
                    modifier = Modifier.width(twoDigitWidth),
                    text = String.format("%02d", hours),
                    style = captionStyle,
                    textAlign = TextAlign.Center
                )

                Text(
                    text = ":",
                    style = captionStyle,
                    textAlign = TextAlign.Center,
                )

                Text(
                    modifier = Modifier.width(twoDigitWidth),
                    text = String.format("%02d", minutes),
                    style = captionStyle,
                    textAlign = TextAlign.Center,
                )

                Text(
                    text = ":",
                    style = captionStyle,
                    textAlign = TextAlign.Center,
                )

                Text(
                    modifier = Modifier.width(twoDigitWidth),
                    text = String.format("%02d", seconds),
                    style = captionStyle,
                    textAlign = TextAlign.Center
                )
            }
        }

    }
}