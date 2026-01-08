package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.DisabledContentGray
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutSchedule

@Composable
fun ActiveScheduleCard(
    schedule: WorkoutSchedule,
    index: Int,
    workout: Workout
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(5.dp)
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = if (schedule.label.isNotEmpty()) schedule.label else "Schedule ${index + 1}",
                    style = MaterialTheme.typography.bodyMedium,
                    color = if (schedule.isEnabled) MaterialTheme.colorScheme.onBackground else DisabledContentGray
                )
                Text(
                    text = if (schedule.specificDate != null) {
                        "On ${schedule.specificDate} at ${schedule.hour}:${schedule.minute.toString().padStart(2, '0')}"
                    } else {
                        val days = getDaysOfWeekStringForSchedule(schedule.daysOfWeek)
                        "$days at ${schedule.hour}:${schedule.minute.toString().padStart(2, '0')}"
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = if (schedule.isEnabled) MaterialTheme.colorScheme.onBackground else DisabledContentGray
                )
            }
            Text(
                text = if (schedule.isEnabled) "Enabled" else "Disabled",
                style = MaterialTheme.typography.bodySmall,
                color = if (schedule.isEnabled) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

fun getDaysOfWeekStringForSchedule(daysOfWeek: Int): String {
    val dayPairs = listOf(
        1 to "Sun", 2 to "Mon", 4 to "Tue", 8 to "Wed",
        16 to "Thu", 32 to "Fri", 64 to "Sat"
    )
    val days = dayPairs.filter { (bit, _) -> (daysOfWeek and bit) != 0 }.map { it.second }
    return when {
        days.isEmpty() -> "No days selected"
        days.size == 7 -> "Every day"
        days.size == 5 && !days.contains("Sat") && !days.contains("Sun") -> "Weekdays"
        days.size == 2 && days.contains("Sat") && days.contains("Sun") -> "Weekends"
        else -> days.joinToString(", ")
    }
}




