package com.gabstra.myworkoutassistant.composables

import android.annotation.SuppressLint
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AccessTimeFilled
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
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.Icon
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.LighterGray
import com.gabstra.myworkoutassistant.shared.MediumLighterGray
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
    val screenState by viewModel.screenState.collectAsState()
    val displayMode = screenState.headerDisplayMode
    val startWorkoutTime = screenState.startWorkoutTime
    var duration by remember { mutableStateOf(Duration.ZERO) }
    val context = LocalContext.current

    if(displayMode == 1 && startWorkoutTime != null){
        LaunchedEffect(Unit) {
            while (true) {
                val now = LocalDateTime.now()
                duration = Duration.between(startWorkoutTime,now)
                val nextSecond = now.plusSeconds(1).truncatedTo(ChronoUnit.SECONDS)
                delay(Duration.between(now, nextSecond).toMillis())
            }
        }
    }

    val interactionSource = remember { MutableInteractionSource() }

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .offset(y = 10.dp)
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
                Text(
                    modifier = Modifier.alignByBaseline(),
                    text = " | ",
                    style = MaterialTheme.typography.labelMedium.copy(fontWeight = FontWeight.Thin),
                    color = MediumLighterGray
                )
                CurrentTime()
            }
        }else{
            val captionStyle = MaterialTheme.typography.bodyMedium.copy(
                fontWeight = FontWeight.Medium
            )

            val hours = remember(duration) { duration.toHours() }
            val minutes = remember(duration) { duration.toMinutes() % 60 }
            val seconds = remember(duration) { duration.seconds % 60 }

            val clockText = remember(hours, minutes, seconds) {
                buildAnnotatedString {
                    append(String.format("%02d", hours))
                    append(":")
                    append(String.format("%02d", minutes))
                    append(":")
                    append(String.format("%02d", seconds))
                }
            }

            Row(
                horizontalArrangement = Arrangement.spacedBy(5.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Icon(
                    modifier = Modifier.size(15.dp),
                    imageVector = Icons.Filled.AccessTimeFilled,
                    contentDescription = "clock",
                )
                Text(
                    text = clockText,
                    style = captionStyle,
                    textAlign = TextAlign.Center
                )
            }
        }
    }
}