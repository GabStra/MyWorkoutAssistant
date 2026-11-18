package com.gabstra.myworkoutassistant.screens

import android.content.Context
import androidx.annotation.StringRes
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.WorkoutTypes
import com.gabstra.myworkoutassistant.shared.HeartRateSource
import com.gabstra.myworkoutassistant.shared.WorkoutSchedule
import com.gabstra.myworkoutassistant.shared.utils.ScheduleConflictChecker

@StringRes
fun HeartRateSource.labelRes(): Int = when (this) {
    HeartRateSource.WATCH_SENSOR -> R.string.loc_form_audit_hr_source_watch_sensor
    HeartRateSource.POLAR_BLE -> R.string.loc_form_audit_hr_source_polar
    HeartRateSource.WHOOP_BLE -> R.string.loc_form_audit_hr_source_whoop
}

fun HeartRateSource.localizedLabel(context: Context): String = context.getString(labelRes())

/** Localizes known Health Connect exercise types while keeping any persisted fallback label. */
fun localizedExternalExerciseTypeLabel(
    context: Context,
    exerciseType: Int,
    persistedLabel: String,
): String = WorkoutTypes.GetStringResourceFromInt(exerciseType)
    ?.let { context.getString(it) }
    ?: persistedLabel

/**
 * Formats schedule conflicts for mobile display using the same conflict list produced by the
 * shared checker. Only presentation changes here; detection and selection of conflicts stay in
 * [ScheduleConflictChecker].
 */
fun formatScheduleConflictMessage(
    context: Context,
    conflicts: List<ScheduleConflictChecker.ScheduleConflict>,
): String {
    if (conflicts.isEmpty()) return ""

    val conflictDetails = conflicts.take(3).joinToString(", ") { conflict ->
        context.getString(
            R.string.loc_form_audit_conflict_pair,
            formatScheduleTime(context, conflict.schedule1),
            formatScheduleTime(context, conflict.schedule2),
        )
    }
    val moreCount = conflicts.size - 3
    val moreText = if (moreCount > 0) {
        " " + context.resources.getQuantityString(
            R.plurals.loc_form_audit_conflict_more,
            moreCount,
            moreCount,
        )
    } else {
        ""
    }
    return context.getString(
        R.string.loc_form_audit_conflict_message,
        conflictDetails + moreText,
    )
}

private fun formatScheduleTime(context: Context, schedule: WorkoutSchedule): String {
    val time = "${schedule.hour}:${schedule.minute.toString().padStart(2, '0')}"
    val day = when {
        schedule.specificDate != null -> schedule.specificDate.toString()
        schedule.daysOfWeek > 0 -> context.getString(R.string.loc_form_audit_conflict_day_recurring)
        else -> context.getString(R.string.loc_form_audit_conflict_day_unknown)
    }
    return context.getString(R.string.loc_form_audit_conflict_schedule_time, time, day)
}
