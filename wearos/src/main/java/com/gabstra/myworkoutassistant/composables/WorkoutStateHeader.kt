package com.gabstra.myworkoutassistant.composables

import android.annotation.SuppressLint
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
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
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workout.timer.WorkoutTimerService
import kotlinx.coroutines.delay
import java.time.Duration
import java.time.LocalDateTime
import java.time.temporal.ChronoUnit

@Composable
private fun rememberHeaderClockTime(enabled: Boolean): LocalDateTime {
    var currentTime by remember { mutableStateOf(LocalDateTime.now()) }

    LaunchedEffect(enabled) {
        if (!enabled) return@LaunchedEffect

        while (true) {
            val now = LocalDateTime.now()
            currentTime = now
            val nextSecond = now.truncatedTo(ChronoUnit.SECONDS).plusSeconds(1)
            val delayMillis = Duration.between(now, nextSecond).toMillis().coerceAtLeast(1L)
            delay(delayMillis)
        }
    }

    return currentTime
}

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
    val restState = workoutState as? WorkoutState.Rest
    val setState = workoutState as? WorkoutState.Set
    val showRestTimerInHeader = restState != null && !screenState.isRestTimerPageVisible
    val isTimedOrEnduranceSet = setState?.currentSetData?.let { setData ->
        setData is TimedDurationSetData || setData is EnduranceSetData
    } ?: false
    val showSetTimerInHeader = isTimedOrEnduranceSet && !screenState.isExerciseDetailPageVisible
    val restSetData = restState?.currentSetData as? RestSetData
    var restTimerUiState by remember(restState?.set?.id) {
        mutableStateOf<WorkoutTimerService.TimerUiState?>(null)
    }
    var setTimerUiState by remember(setState?.set?.id) {
        mutableStateOf<WorkoutTimerService.TimerUiState?>(null)
    }

    LaunchedEffect(restState?.set?.id) {
        restTimerUiState = null
    }
    LaunchedEffect(setState?.set?.id) {
        setTimerUiState = null
    }
    LaunchedEffect(showRestTimerInHeader, restState?.set?.id) {
        if (!showRestTimerInHeader) return@LaunchedEffect
        val activeRestState = restState
        viewModel.workoutTimerService.timerUiState(activeRestState.set.id).collect { latest ->
            restTimerUiState = latest
        }
    }
    LaunchedEffect(showSetTimerInHeader, setState?.set?.id) {
        if (!showSetTimerInHeader) return@LaunchedEffect
        val activeSetState = setState
        viewModel.workoutTimerService.timerUiState(activeSetState.set.id).collect { latest ->
            setTimerUiState = latest
        }
    }

    val interactionSource = remember { MutableInteractionSource() }
    val restTimerSeconds = restTimerUiState?.displaySeconds ?: restSetData?.endTimer ?: 0
    val setTimerSeconds = when {
        setTimerUiState != null -> setTimerUiState!!.displaySeconds
        setState?.currentSetData is TimedDurationSetData ->
            ((setState.currentSetData as TimedDurationSetData).endTimer / 1000).coerceAtLeast(0)
        setState?.currentSetData is EnduranceSetData ->
            ((setState.currentSetData as EnduranceSetData).endTimer / 1000).coerceAtLeast(0)
        else -> 0
    }
    val shouldShowSetTimer = showSetTimerInHeader
    val showWorkoutElapsedTime = !showRestTimerInHeader && !shouldShowSetTimer && displayMode != 0
    val headerClockTime = rememberHeaderClockTime(enabled = showWorkoutElapsedTime)

    Row(
        modifier = modifier
            .fillMaxSize()
            .clickable(
                interactionSource = interactionSource,
                indication = null
            ) {
                if (
                    workoutState is WorkoutState.Preparing ||
                    showRestTimerInHeader ||
                    shouldShowSetTimer
                ) return@clickable
                viewModel.switchHeaderDisplayMode()
                hapticsViewModel.doGentleVibration()
            },
        horizontalArrangement = Arrangement.Center
    ) {
        if (showRestTimerInHeader) {
            Row(
                modifier = Modifier.padding(top = 5.dp),
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
        } else if (shouldShowSetTimer) {
            Row(
                modifier = Modifier.padding(top = 5.dp),
                horizontalArrangement = Arrangement.spacedBy(5.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Icon(
                    modifier = Modifier.size(15.dp),
                    imageVector = Icons.Filled.AccessTimeFilled,
                    contentDescription = "set timer",
                )
                TimeViewer(
                    seconds = setTimerSeconds.coerceAtLeast(0),
                    color = MaterialTheme.colorScheme.onBackground,
                    style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Medium)
                )
            }
        } else if (displayMode == 0) {
            Row(
                modifier = Modifier.padding(top = 5.dp),
                verticalAlignment = Alignment.CenterVertically
            ){
                CurrentBattery()
                Text(
                    modifier = Modifier.alignByBaseline(),
                    text = " | ",
                    style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Medium),
                    color = MediumLighterGray
                )
                CurrentTime()
            }
        }else{
            val captionStyle = MaterialTheme.typography.bodyMedium.copy(
                fontWeight = FontWeight.Medium
            )

            val durationSeconds = screenState.startWorkoutTime?.let { startTime ->
                Duration.between(startTime, headerClockTime)
                    .seconds
                    .coerceAtLeast(0L)
            } ?: 0L
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
                modifier = Modifier.padding(top = 5.dp),
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
