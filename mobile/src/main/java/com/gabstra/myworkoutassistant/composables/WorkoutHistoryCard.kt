package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.size
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
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.shared.DisabledContentGray
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.workout.ui.InterruptedWorkoutCopy
import java.time.format.DateTimeFormatter

@Composable
fun WorkoutHistoryCard(
    workoutHistory: WorkoutHistory,
    workout: Workout,
    appViewModel: AppViewModel,
    timeFormatter: DateTimeFormatter
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

        Text(
            modifier = Modifier
                .weight(1f)
                .basicMarquee(iterations = Int.MAX_VALUE),
            text = if (workoutHistory.isDone) workout.name else "${workout.name} ${InterruptedWorkoutCopy.SUFFIX}",
            color = if (workout.enabled) MaterialTheme.colorScheme.onBackground else DisabledContentGray,
            style = MaterialTheme.typography.bodyLarge,
        )

        if (workoutHistory.isDone) {
            Text(
                text = workoutHistory.time.format(timeFormatter),
                textAlign = TextAlign.End,
                color = MaterialTheme.colorScheme.onBackground,
                style = MaterialTheme.typography.bodyLarge,
            )
        }
    }
}
