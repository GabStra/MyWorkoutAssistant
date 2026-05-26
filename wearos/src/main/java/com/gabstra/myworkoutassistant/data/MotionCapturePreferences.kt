package com.gabstra.myworkoutassistant.data

import android.content.Context
import androidx.core.content.edit

object MotionCapturePreferences {
    private const val PREFS_NAME = "motion_capture_prefs"
    private const val KEY_RECORD_MOTION_DATASET = "record_motion_dataset"

    fun isEnabled(context: Context): Boolean =
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .getBoolean(KEY_RECORD_MOTION_DATASET, false)

    fun setEnabled(context: Context, enabled: Boolean) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit {
            putBoolean(KEY_RECORD_MOTION_DATASET, enabled)
        }
    }
}
