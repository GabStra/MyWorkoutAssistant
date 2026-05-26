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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.shared.DisabledContentGray
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.workout.model.WorkoutSessionStatus
import com.gabstra.myworkoutassistant.shared.workout.model.workoutSessionDisplayLabel
import java.time.format.DateTimeFormatter

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
        horizontalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        IconButton(
            modifier = Modifier.clip(CircleShape).size(35.dp),
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
                tint = MaterialTheme.colorScheme.onBackground
            )
        }

        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(4.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text(
                    modifier = Modifier.weight(1f),
                    text = workout.name,
                    color = if (workout.enabled) MaterialTheme.colorScheme.onBackground else DisabledContentGray,
                    style = MaterialTheme.typography.bodyLarge,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )

                if (workoutHistory.isDone) {
                    Text(
                        text = buildString {
                            append(workoutHistory.startTime.toLocalTime().format(timeFormatter))
                            append("-")
                            append(
                                workoutHistory.startTime
                                    .plusSeconds(workoutHistory.duration.toLong())
                                    .toLocalTime()
                                    .format(timeFormatter)
                            )
                        },
                        textAlign = TextAlign.End,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }
            }

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                workoutSessionDisplayLabel(sessionStatus)?.let { label ->
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
        }
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
