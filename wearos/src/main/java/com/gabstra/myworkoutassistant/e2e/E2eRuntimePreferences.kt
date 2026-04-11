package com.gabstra.myworkoutassistant.e2e

import android.content.Context

object E2eRuntimePreferences {
    const val PREFS_NAME = "e2e_prefs"
    private const val KEY_DISABLE_STARTUP_UNSYNCED_HISTORY_SYNC =
        "disable_startup_unsynced_history_sync"
    private const val KEY_WORKOUT_HISTORY_SYNC_DEBOUNCE_MS =
        "workout_history_sync_debounce_ms"
    private const val KEY_FORCE_AMBIENT_WORKOUT_OVERLAY =
        "force_ambient_workout_overlay"

    fun isStartupUnsyncedHistorySyncDisabled(context: Context): Boolean {
        return context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .getBoolean(KEY_DISABLE_STARTUP_UNSYNCED_HISTORY_SYNC, false)
    }

    fun setStartupUnsyncedHistorySyncDisabled(context: Context, disabled: Boolean) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putBoolean(KEY_DISABLE_STARTUP_UNSYNCED_HISTORY_SYNC, disabled)
            .commit()
    }

    fun getWorkoutHistorySyncDebounceMs(context: Context): Long? {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        return if (prefs.contains(KEY_WORKOUT_HISTORY_SYNC_DEBOUNCE_MS)) {
            prefs.getLong(KEY_WORKOUT_HISTORY_SYNC_DEBOUNCE_MS, 0L)
        } else {
            null
        }
    }

    fun setWorkoutHistorySyncDebounceMs(context: Context, debounceMs: Long) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putLong(KEY_WORKOUT_HISTORY_SYNC_DEBOUNCE_MS, debounceMs)
            .commit()
    }

    fun isAmbientWorkoutOverlayForced(context: Context): Boolean {
        return context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .getBoolean(KEY_FORCE_AMBIENT_WORKOUT_OVERLAY, false)
    }

    fun setAmbientWorkoutOverlayForced(context: Context, forced: Boolean) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putBoolean(KEY_FORCE_AMBIENT_WORKOUT_OVERLAY, forced)
            .commit()
    }

    fun clear(context: Context) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .remove(KEY_DISABLE_STARTUP_UNSYNCED_HISTORY_SYNC)
            .remove(KEY_WORKOUT_HISTORY_SYNC_DEBOUNCE_MS)
            .remove(KEY_FORCE_AMBIENT_WORKOUT_OVERLAY)
            .commit()
    }
}
