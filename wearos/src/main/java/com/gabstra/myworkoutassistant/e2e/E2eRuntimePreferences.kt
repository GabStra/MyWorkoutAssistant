package com.gabstra.myworkoutassistant.e2e

import android.content.Context

object E2eRuntimePreferences {
    const val PREFS_NAME = "e2e_prefs"
    private const val KEY_DISABLE_STARTUP_UNSYNCED_HISTORY_SYNC =
        "disable_startup_unsynced_history_sync"

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

    fun clear(context: Context) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .remove(KEY_DISABLE_STARTUP_UNSYNCED_HISTORY_SYNC)
            .commit()
    }
}
