package com.gabstra.myworkoutassistant.e2e.helpers

import android.content.Context

object WorkoutHeartbeatCrossDeviceObservationState {
    private const val PREFS_NAME = "workout_heartbeat_cross_device_observation"
    private const val PASSED_KEY = "passed"
    private const val DETAILS_KEY = "details"

    fun clear(context: Context) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .clear()
            .commit()
    }

    fun markPassed(context: Context, details: String) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putBoolean(PASSED_KEY, true)
            .putString(DETAILS_KEY, details)
            .commit()
    }

    fun hasPassed(context: Context): Boolean {
        return context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .getBoolean(PASSED_KEY, false)
    }

    fun details(context: Context): String? {
        return context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .getString(DETAILS_KEY, null)
    }
}
