package com.gabstra.myworkoutassistant.insights

import android.content.Context
import com.gabstra.myworkoutassistant.MobileLlmFeatureFlags
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf

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
        if (!MobileLlmFeatureFlags.ENABLED) {
            return flowOf(
                WorkoutInsightsChunk(
                    title = request.title,
                    text = "LLM features are temporarily disabled.",
                    phase = WorkoutInsightsPhase.FINAL_SYNTHESIS,
                    statusText = "LLM features are temporarily disabled."
                )
            )
        }
        val preparedRequest = request.withConfiguredCustomInstructions()
        return when (WorkoutInsightsSettingsStore.getMode(context)) {
            WorkoutInsightsMode.LOCAL -> localEngine.generateInsights(preparedRequest)
            WorkoutInsightsMode.REMOTE -> remoteEngine.generateInsights(preparedRequest)
        }
    }

    private fun WorkoutInsightsRequest.withConfiguredCustomInstructions(): WorkoutInsightsRequest {
        if (customInstructions.isNotBlank()) return this
        if (toolContext == null) return this
        val configuredInstructions = WorkoutInsightsSettingsStore.getCustomInstructions(context)
        return if (configuredInstructions.isBlank()) {
            this
        } else {
            copy(customInstructions = configuredInstructions)
        }
    }
}
