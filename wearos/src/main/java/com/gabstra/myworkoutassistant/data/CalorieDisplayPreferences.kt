package com.gabstra.myworkoutassistant.data

import android.content.Context
import androidx.core.content.edit

object CalorieDisplayPreferences {
    private const val PREFS_NAME = "calorie_display_prefs"
    private const val KEY_SHOW_CALORIES = "show_calories_on_timed_sets"
    const val DEFAULT_CALORIES_ENABLED = true

    fun isEnabled(context: Context): Boolean =
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .getBoolean(KEY_SHOW_CALORIES, DEFAULT_CALORIES_ENABLED)

    fun setEnabled(context: Context, enabled: Boolean) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit {
            putBoolean(KEY_SHOW_CALORIES, enabled)
        }
    }
}
