package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Info
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.shared.DisabledContentGray
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryOrigin
import com.gabstra.myworkoutassistant.shared.workout.history.knownDurationSecondsOrNull
import com.gabstra.myworkoutassistant.shared.workout.history.knownStartTimeOrNull
import com.gabstra.myworkoutassistant.shared.workout.model.WorkoutSessionStatus
import com.gabstra.myworkoutassistant.shared.workout.model.completedWorkoutEndDisplayLabel
import com.gabstra.myworkoutassistant.shared.workout.model.workoutSessionDisplayLabel
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle

@Composable
fun WorkoutHistoryCard(
    workoutHistory: WorkoutHistory,
    workout: Workout,
    appViewModel: AppViewModel,
    timeFormatter: DateTimeFormatter,
    sessionStatus: WorkoutSessionStatus? = null,
    statusBadgeText: String? = null,
) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(Spacing.sm)
    ) {
        IconButton(
            modifier = Modifier.clip(CircleShape).size(40.dp),
            onClick = {
                appViewModel.setScreenData(
                    ScreenData.WorkoutHistory(
                        workout.id,
                        workoutHistory.id
                    )
                )
            }
        ) {
            Icon(
                imageVector = Icons.Filled.Info,
                contentDescription = "View details",
                modifier = Modifier.size(20.dp),
                tint = MaterialTheme.colorScheme.onBackground
            )
        }

        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(4.dp)
        ) {
            Text(
                modifier = Modifier.fillMaxWidth(),
                text = workout.name,
                color = if (workout.enabled) MaterialTheme.colorScheme.onBackground else DisabledContentGray,
                style = MaterialTheme.typography.bodyLarge,
            )

            val startTime = workoutHistory.knownStartTimeOrNull()
            val durationSeconds = workoutHistory.knownDurationSecondsOrNull()
            val dateFormatter = DateTimeFormatter.ofLocalizedDate(FormatStyle.MEDIUM)
                .withLocale(timeFormatter.locale)
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = buildString {
                        append(workoutHistory.date.format(dateFormatter))
                        startTime?.let { start ->
                            append(" · ")
                            append(start.toLocalTime().format(timeFormatter))
                            if (workoutHistory.isDone && durationSeconds != null) {
                                append("–")
                                append(start.plusSeconds(durationSeconds.toLong()).toLocalTime().format(timeFormatter))
                            }
                        }
                    },
                    modifier = Modifier.weight(1f),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodyMedium,
                )
                durationSeconds?.takeIf { startTime == null }?.let { duration ->
                    SessionInfoPill(
                        text = "Duration ${formatTime(duration)}",
                        backgroundColor = MaterialTheme.colorScheme.surfaceVariant,
                        contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                workoutSessionDisplayLabel(sessionStatus)?.let { label ->
                    SessionInfoPill(
                        text = label,
                        backgroundColor = MaterialTheme.colorScheme.surfaceVariant,
                        contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                completedWorkoutEndDisplayLabel(workoutHistory)?.let { label ->
                    SessionInfoPill(
                        text = label,
                        backgroundColor = MaterialTheme.colorScheme.surfaceVariant,
                        contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                if (statusBadgeText != null) {
                    SessionInfoPill(
                        text = statusBadgeText,
                        backgroundColor = MaterialTheme.colorScheme.surfaceVariant,
                        contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            WorkoutHistoryOriginDetails(workoutHistory)
        }
    }
}

fun workoutHistoryDateTimeLabel(
    workoutHistory: WorkoutHistory,
    dateFormatter: DateTimeFormatter,
    timeFormatter: DateTimeFormatter,
): String = buildString {
    append(workoutHistory.date.format(dateFormatter))
    workoutHistory.knownStartTimeOrNull()?.let { startTime ->
        append(" ")
        append(startTime.toLocalTime().format(timeFormatter))
    }
}

@Composable
fun WorkoutHistoryOriginDetails(
    workoutHistory: WorkoutHistory,
) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        SessionInfoPill(
            text = when (workoutHistory.origin) {
                WorkoutHistoryOrigin.RECORDED -> "Recorded"
                WorkoutHistoryOrigin.USER_IMPORTED -> "User imported"
            },
            backgroundColor = MaterialTheme.colorScheme.surfaceVariant,
            contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
fun SessionInfoPill(
    text: String,
    backgroundColor: androidx.compose.ui.graphics.Color,
    contentColor: androidx.compose.ui.graphics.Color,
) {
    Text(
        modifier = Modifier
            .background(
                color = backgroundColor,
                shape = RoundedCornerShape(999.dp)
            )
            .padding(horizontal = 8.dp, vertical = 2.dp),
        text = text,
        color = contentColor,
        style = MaterialTheme.typography.labelSmall,
    )
}
