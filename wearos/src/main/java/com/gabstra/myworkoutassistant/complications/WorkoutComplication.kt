package com.gabstra.myworkoutassistant.complications

import android.content.ComponentName
import android.content.Context
import android.content.SharedPreferences
import androidx.wear.watchface.complications.datasource.ComplicationDataSourceUpdateRequester
import com.gabstra.myworkoutassistant.shared.workout.timer.WorkoutTimerService
import java.util.Locale

/**
 * Publishes the active workout timer to [WorkoutTimerComplicationService].
 *
 * The Now Bar cue on the watch face is icon-only, so a complication is the only way to show the
 * countdown there. A base wall-clock time is stored instead of a remaining-seconds value so the
 * data source keeps counting even while the app process isn't running.
 */
object WorkoutComplication {

    private const val PREFS = "workout_complication"
    private const val KEY_ACTIVE = "active"
    private const val KEY_RUNNING = "running"
    private const val KEY_COUNTDOWN = "countdown"
    private const val KEY_BASE_WALL_CLOCK = "base_wall_clock"
    private const val KEY_FIXED_VALUE = "fixed_value"
    private const val KEY_LABEL = "label"
    private const val KEY_LAST_VALUE = "last_value"

    private fun prefs(context: Context): SharedPreferences =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    /** Called from the workout screen on every timer tick (the timer emits at 5 Hz). */
    fun update(context: Context, state: WorkoutTimerService.TimerUiState?) {
        val prefs = prefs(context)
        val editor = prefs.edit()
        if (state == null) {
            editor.putBoolean(KEY_ACTIVE, true)
                .putBoolean(KEY_RUNNING, false)
                .putString(KEY_FIXED_VALUE, "Active")
                .putString(KEY_LABEL, "Workout")
        } else {
            val label = labelFor(state.timerType)
            if (state.isRunning) {
                val countdown = state.timerType != WorkoutTimerService.TimerType.ENDURANCE_SET
                val now = System.currentTimeMillis()
                val base = if (countdown) {
                    now + state.displayMillis
                } else {
                    now - state.displayMillis
                }
                editor.putBoolean(KEY_ACTIVE, true)
                    .putBoolean(KEY_RUNNING, true)
                    .putBoolean(KEY_COUNTDOWN, countdown)
                    .putLong(KEY_BASE_WALL_CLOCK, base)
                    .putString(KEY_LABEL, label)
            } else {
                editor.putBoolean(KEY_ACTIVE, true)
                    .putBoolean(KEY_RUNNING, false)
                    .putString(KEY_FIXED_VALUE, format(state.displayMillis))
                    .putString(KEY_LABEL, label)
            }
        }
        editor.apply()

        val value = currentValue(context) ?: return
        if (prefs.getString(KEY_LAST_VALUE, null) != value) {
            prefs.edit().putString(KEY_LAST_VALUE, value).apply()
            requestUpdate(context)
        }
    }

    fun clear(context: Context) {
        prefs(context).edit()
            .putBoolean(KEY_ACTIVE, false)
            .remove(KEY_LAST_VALUE)
            .apply()
        requestUpdate(context)
    }

    fun currentValue(context: Context): String? {
        val prefs = prefs(context)
        if (!prefs.getBoolean(KEY_ACTIVE, false)) return null
        if (!prefs.getBoolean(KEY_RUNNING, false)) return prefs.getString(KEY_FIXED_VALUE, null)
        val remaining = prefs.getLong(KEY_BASE_WALL_CLOCK, 0L) - System.currentTimeMillis()
        return format(if (prefs.getBoolean(KEY_COUNTDOWN, true)) remaining else -remaining)
    }

    fun currentLabel(context: Context): String =
        prefs(context).getString(KEY_LABEL, null) ?: "Workout"

    private fun requestUpdate(context: Context) {
        ComplicationDataSourceUpdateRequester.create(
            context,
            ComponentName(context, WorkoutTimerComplicationService::class.java)
        ).requestUpdateAll()
    }

    private fun labelFor(type: WorkoutTimerService.TimerType): String = when (type) {
        WorkoutTimerService.TimerType.REST -> "Rest"
        WorkoutTimerService.TimerType.TIMED_DURATION_SET -> "Set"
        WorkoutTimerService.TimerType.ENDURANCE_SET -> "Elapsed"
        WorkoutTimerService.TimerType.SUPERSET_CAP -> "Time left"
        WorkoutTimerService.TimerType.SUPERSET_ROUND_CADENCE -> "Round"
    }

    private fun format(millis: Int): String = format(millis.toLong())

    private fun format(millis: Long): String {
        val totalSeconds = (kotlin.math.abs(millis) / 1000).coerceAtLeast(0)
        val hours = totalSeconds / 3600
        val minutes = (totalSeconds % 3600) / 60
        val seconds = totalSeconds % 60
        return if (hours > 0) {
            String.format(Locale.US, "%d:%02d:%02d", hours, minutes, seconds)
        } else {
            String.format(Locale.US, "%02d:%02d", minutes, seconds)
        }
    }
}
