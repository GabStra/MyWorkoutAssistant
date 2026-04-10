package com.gabstra.myworkoutassistant.insights

import android.content.Context
import androidx.core.content.edit

private const val INSIGHTS_PREFS = "litert_lm_insights"
private const val MODE_KEY = "mode"
private const val REMOTE_BASE_URL_KEY = "remote_base_url"
private const val REMOTE_API_KEY_KEY = "remote_api_key"
private const val REMOTE_MODEL_KEY = "remote_model"

object WorkoutInsightsSettingsStore {
    fun getMode(context: Context): WorkoutInsightsMode =
        WorkoutInsightsMode.fromStoredValue(
            context.getSharedPreferences(INSIGHTS_PREFS, Context.MODE_PRIVATE)
                .getString(MODE_KEY, null)
        )

    fun setMode(
        context: Context,
        mode: WorkoutInsightsMode,
    ) {
        context.getSharedPreferences(INSIGHTS_PREFS, Context.MODE_PRIVATE).edit {
            putString(MODE_KEY, mode.name)
        }
    }

    fun getRemoteConfig(context: Context): RemoteOpenAiConfig {
        val prefs = context.getSharedPreferences(INSIGHTS_PREFS, Context.MODE_PRIVATE)
        return RemoteOpenAiConfig(
            baseUrl = prefs.getString(REMOTE_BASE_URL_KEY, null).orEmpty(),
            apiKey = prefs.getString(REMOTE_API_KEY_KEY, null).orEmpty(),
            model = prefs.getString(REMOTE_MODEL_KEY, null).orEmpty(),
        )
    }

    fun setRemoteConfig(
        context: Context,
        config: RemoteOpenAiConfig,
    ) {
        context.getSharedPreferences(INSIGHTS_PREFS, Context.MODE_PRIVATE).edit {
            putString(REMOTE_BASE_URL_KEY, config.baseUrl.trim())
            putString(REMOTE_API_KEY_KEY, config.apiKey.trim())
            putString(REMOTE_MODEL_KEY, config.model.trim())
        }
    }

    fun clearRemoteConfig(context: Context) {
        context.getSharedPreferences(INSIGHTS_PREFS, Context.MODE_PRIVATE).edit {
            remove(REMOTE_BASE_URL_KEY)
            remove(REMOTE_API_KEY_KEY)
            remove(REMOTE_MODEL_KEY)
        }
    }

    fun getConfigurationState(context: Context): WorkoutInsightsConfigurationState {
        val mode = getMode(context)
        return when (mode) {
            WorkoutInsightsMode.LOCAL -> WorkoutInsightsConfigurationState(
                mode = mode,
                modeLabel = mode.label,
                isConfigured = LiteRtLmModelStore.getConfiguredModelPath(context) != null,
                missingConfigurationMessage = "No LiteRT-LM model is configured. Import a local .litertlm model file to enable on-device insights.",
                configureActionLabel = "Import model",
            )
            WorkoutInsightsMode.REMOTE -> {
                val config = getRemoteConfig(context)
                WorkoutInsightsConfigurationState(
                    mode = mode,
                    modeLabel = mode.label,
                    isConfigured = config.isComplete(),
                    missingConfigurationMessage = "Remote insights are selected, but the base URL, API key, or model is missing. Configure them in Settings to enable the hosted OpenAI API.",
                    configureActionLabel = null,
                )
            }
        }
    }
}
