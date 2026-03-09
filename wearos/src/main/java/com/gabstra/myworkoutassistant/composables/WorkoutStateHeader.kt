package com.gabstra.myworkoutassistant.composables

import android.annotation.SuppressLint
import android.os.SystemClock
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
import androidx.compose.runtime.mutableLongStateOf
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
import com.gabstra.myworkoutassistant.shared.workout.timer.WorkoutTimerService
import kotlinx.coroutines.delay
import java.time.Duration
import java.time.LocalDateTime

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
    var durationSeconds by remember(startWorkoutTime) { mutableLongStateOf(0L) }
    var restTimerUiState by remember(restState?.set?.id) {
        mutableStateOf<WorkoutTimerService.TimerUiState?>(null)
    }

    LaunchedEffect(restState?.set?.id) {
        restTimerUiState = null
    }
    LaunchedEffect(showRestTimerInHeader, restState?.set?.id) {
        if (!showRestTimerInHeader) return@LaunchedEffect
        val activeRestState = restState ?: return@LaunchedEffect
        viewModel.workoutTimerService.timerUiState(activeRestState.set.id).collect { latest ->
            restTimerUiState = latest
        }
    }

    if (displayMode == 1 && startWorkoutTime != null) {
        LaunchedEffect(displayMode, startWorkoutTime) {
            val initialElapsedMs = Duration.between(startWorkoutTime, LocalDateTime.now())
                .toMillis()
                .coerceAtLeast(0L)
            val baselineRealtimeMs = SystemClock.elapsedRealtime()

            while (true) {
                val nowRealtimeMs = SystemClock.elapsedRealtime()
                val elapsedMs = initialElapsedMs + (nowRealtimeMs - baselineRealtimeMs)
                durationSeconds = (elapsedMs / 1000L).coerceAtLeast(0L)

                val delayMs = (200L - (nowRealtimeMs % 200L)).coerceAtLeast(1L)
                delay(delayMs)
            }
        }
    }

    val interactionSource = remember { MutableInteractionSource() }
    val restTimerSeconds = restTimerUiState?.displaySeconds ?: restSetData?.endTimer ?: 0

    Row(
        modifier = modifier
            .fillMaxWidth()
            .clickable(
                //interactionSource = interactionSource,
                //indication = null
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

            val hours = remember(durationSeconds) { durationSeconds / 3600L }
            val minutes = remember(durationSeconds) { (durationSeconds % 3600L) / 60L }
            val seconds = remember(durationSeconds) { durationSeconds % 60L }

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
