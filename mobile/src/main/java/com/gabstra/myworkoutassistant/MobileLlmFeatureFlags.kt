package com.gabstra.myworkoutassistant

import android.content.Context
import com.gabstra.myworkoutassistant.insights.WorkoutInsightsSettingsStore

internal object MobileLlmFeatureFlags {
    fun isEnabled(context: Context): Boolean =
        WorkoutInsightsSettingsStore.isEnabled(context.applicationContext)
}
