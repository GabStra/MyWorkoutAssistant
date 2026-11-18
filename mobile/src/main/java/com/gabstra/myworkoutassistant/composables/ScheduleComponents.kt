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
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.R
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
                    text = if (schedule.label.isNotEmpty()) {
                        schedule.label
                    } else {
                        stringResource(R.string.loc_schedule_n, index + 1)
                    },
                    style = MaterialTheme.typography.bodyMedium,
                    color = if (schedule.isEnabled) MaterialTheme.colorScheme.onBackground else DisabledContentGray
                )
                val specificDate = schedule.specificDate
                Text(
                    text = if (specificDate != null) {
                        stringResource(
                            R.string.workout_form_alarm_on_date_at_time,
                            specificDate,
                            "${schedule.hour}:${schedule.minute.toString().padStart(2, '0')}"
                        )
                    } else {
                        val days = getDaysOfWeekStringForSchedule(schedule.daysOfWeek)
                        stringResource(
                            R.string.workout_form_alarm_days_at_time,
                            days,
                            "${schedule.hour}:${schedule.minute.toString().padStart(2, '0')}"
                        )
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = if (schedule.isEnabled) MaterialTheme.colorScheme.onBackground else DisabledContentGray
                )
            }
            Text(
                text = stringResource(
                    if (schedule.isEnabled) R.string.loc_enabled else R.string.loc_disabled
                ),
                style = MaterialTheme.typography.bodySmall,
                color = if (schedule.isEnabled) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

@Composable
fun getDaysOfWeekStringForSchedule(daysOfWeek: Int): String {
    val dayPairs = listOf(
        1 to R.string.workout_day_sun,
        2 to R.string.workout_day_mon,
        4 to R.string.workout_day_tue,
        8 to R.string.workout_day_wed,
        16 to R.string.workout_day_thu,
        32 to R.string.workout_day_fri,
        64 to R.string.workout_day_sat,
    )
    val selectedDayBits = dayPairs.map { it.first }.filter { bit -> (daysOfWeek and bit) != 0 }
    val days = dayPairs.filter { (bit, _) -> (daysOfWeek and bit) != 0 }
        .map { (_, labelRes) -> stringResource(labelRes) }
    return when {
        days.isEmpty() -> stringResource(R.string.workout_form_alarm_no_days)
        selectedDayBits.size == 7 -> stringResource(R.string.workout_form_alarm_every_day)
        selectedDayBits.size == 5 &&
            selectedDayBits.none { it == 1 || it == 64 } ->
            stringResource(R.string.workout_form_alarm_weekdays)
        selectedDayBits.size == 2 && selectedDayBits.toSet() == setOf(1, 64) ->
            stringResource(R.string.workout_form_alarm_weekends)
        else -> days.joinToString(", ")
    }
}




