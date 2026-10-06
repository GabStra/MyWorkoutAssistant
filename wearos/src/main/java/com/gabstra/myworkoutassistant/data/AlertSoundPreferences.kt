package com.gabstra.myworkoutassistant.data

import android.content.Context
import androidx.core.content.edit

object AlertSoundPreferences {
    private const val PREFS_NAME = "wear_alert_sound_prefs"
    private const val KEY_ALERT_SOUND_ENABLED = "alert_sound_enabled"

    const val DEFAULT_ALERT_SOUND_ENABLED = true

    fun isEnabled(context: Context): Boolean {
        return context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .getBoolean(KEY_ALERT_SOUND_ENABLED, DEFAULT_ALERT_SOUND_ENABLED)
    }

    fun setEnabled(context: Context, enabled: Boolean) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit {
            putBoolean(KEY_ALERT_SOUND_ENABLED, enabled)
        }
    }
}
