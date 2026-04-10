package com.gabstra.myworkoutassistant.insights

import android.content.Context
import kotlinx.coroutines.flow.Flow

enum class WorkoutInsightsMode(
    val label: String,
) {
    LOCAL("Local"),
    REMOTE("Remote");

    companion object {
        val default: WorkoutInsightsMode = LOCAL

        fun fromStoredValue(value: String?): WorkoutInsightsMode =
            entries.firstOrNull { it.name == value } ?: default
    }
}

data class RemoteOpenAiConfig(
    val baseUrl: String = "",
    val apiKey: String = "",
    val model: String = "",
) {
    fun isComplete(): Boolean =
        baseUrl.isNotBlank() && apiKey.isNotBlank() && model.isNotBlank()
}

data class WorkoutInsightsConfigurationState(
    val mode: WorkoutInsightsMode,
    val modeLabel: String,
    val isConfigured: Boolean,
    val missingConfigurationMessage: String,
    val configureActionLabel: String?,
)

interface WorkoutInsightsEngine {
    fun generateInsights(
        request: WorkoutInsightsRequest,
    ): Flow<WorkoutInsightsChunk>
}

class ConfigurableWorkoutInsightsEngine(
    private val context: Context,
) : WorkoutInsightsEngine {
    private val localEngine = LiteRtLmInsightsRepository(context)
    private val remoteEngine = OpenAiInsightsRepository(context)

    override fun generateInsights(
        request: WorkoutInsightsRequest,
    ): Flow<WorkoutInsightsChunk> {
        return when (WorkoutInsightsSettingsStore.getMode(context)) {
            WorkoutInsightsMode.LOCAL -> localEngine.generateInsights(request)
            WorkoutInsightsMode.REMOTE -> remoteEngine.generateInsights(request)
        }
    }
}
