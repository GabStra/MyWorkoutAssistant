package com.gabstra.myworkoutassistant.composables

import android.annotation.SuppressLint
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AccessTimeFilled
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.Icon
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.MediumLighterGray
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import kotlinx.coroutines.delay
import java.time.Duration
import java.time.LocalDateTime
import java.time.temporal.ChronoUnit

@SuppressLint("DefaultLocale")
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun WorkoutStateHeader(
    modifier: Modifier = Modifier,
    workoutState: WorkoutState,
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel
){
    val screenState by viewModel.screenState.collectAsState()
    val displayMode = screenState.headerDisplayMode
    val startWorkoutTime = screenState.startWorkoutTime
    val restState = workoutState as? WorkoutState.Rest
    val showRestTimerInHeader = restState != null && !screenState.isRestTimerPageVisible
    val restSetData = restState?.currentSetData as? RestSetData
    var duration by remember { mutableStateOf(Duration.ZERO) }
    var restTimerSeconds by remember(restState?.set?.id) {
        mutableIntStateOf(restSetData?.endTimer ?: 0)
    }

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
    LaunchedEffect(showRestTimerInHeader, restState?.set?.id, restState?.startTime, restSetData?.startTimer, restSetData?.endTimer) {
        if (!showRestTimerInHeader) return@LaunchedEffect
        val activeRestState = restState ?: return@LaunchedEffect

        while (true) {
            val latestSetData = activeRestState.currentSetData as? RestSetData ?: break
            val seconds = activeRestState.startTime?.let { startTime ->
                val elapsed = Duration.between(startTime, LocalDateTime.now()).seconds.toInt().coerceAtLeast(0)
                (latestSetData.startTimer - elapsed).coerceAtLeast(0)
            } ?: latestSetData.endTimer.coerceAtLeast(0)
            restTimerSeconds = seconds

            val now = LocalDateTime.now()
            val nextSecond = now.plusSeconds(1).truncatedTo(ChronoUnit.SECONDS)
            delay(Duration.between(now, nextSecond).toMillis())
        }
    }

    val interactionSource = remember { MutableInteractionSource() }

    Row(
        modifier = modifier
            .fillMaxWidth()
            .clickable(
                interactionSource = interactionSource,
                indication = null
            ) {
                if(workoutState is WorkoutState.Preparing || showRestTimerInHeader) return@clickable
                viewModel.switchHeaderDisplayMode()
                hapticsViewModel.doGentleVibration()
            },
        horizontalArrangement = Arrangement.Center
    ) {
        if (showRestTimerInHeader) {
            Row(
                horizontalArrangement = Arrangement.spacedBy(5.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Icon(
                    modifier = Modifier.size(15.dp),
                    imageVector = Icons.Filled.AccessTimeFilled,
                    contentDescription = "rest timer",
                )
                TimeViewer(
                    seconds = restTimerSeconds.coerceAtLeast(0),
                    color = MaterialTheme.colorScheme.onBackground,
                    style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Medium)
                )
            }
        } else if(displayMode == 0){
            Row(verticalAlignment = Alignment.CenterVertically){
                CurrentBattery()
                Text(
                    modifier = Modifier.alignByBaseline(),
                    text = " | ",
                    style = MaterialTheme.typography.labelMedium.copy(fontWeight = FontWeight.Normal),
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
