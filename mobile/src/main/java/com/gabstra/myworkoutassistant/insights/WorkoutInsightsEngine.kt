package com.gabstra.myworkoutassistant.insights

import android.content.Context
import com.gabstra.myworkoutassistant.MobileLlmFeatureFlags
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
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
        if (!MobileLlmFeatureFlags.isEnabled(context)) {
            return flowOf(
                WorkoutInsightsChunk(
                    title = request.title,
                    text = "LLM features are temporarily disabled.",
                    phase = WorkoutInsightsPhase.FINAL_SYNTHESIS,
                    statusText = "LLM features are temporarily disabled."
                )
            )
        }
        val mode = WorkoutInsightsSettingsStore.getMode(context)
        val baseRequest = request.withConfiguredCustomInstructions()
        val debugRecorder = baseRequest.debugRecorder ?: createWorkoutInsightsDebugDumpRecorder(
            context = context,
            mode = mode,
            request = baseRequest,
        )
        val preparedRequest = baseRequest.copy(debugRecorder = debugRecorder)
        return flow {
            var lastChunkText = ""
            try {
                val upstream = when (mode) {
                    WorkoutInsightsMode.LOCAL -> localEngine.generateInsights(preparedRequest)
                    WorkoutInsightsMode.REMOTE -> remoteEngine.generateInsights(preparedRequest)
                }
                upstream.collect { chunk ->
                    lastChunkText = chunk.text
                    if (chunk.statusText.isNotBlank()) {
                        debugRecorder.recordStatus(chunk.phase, chunk.statusText)
                    }
                    emit(chunk)
                }
                debugRecorder.finishSuccess(lastChunkText)
            } catch (cancellationException: CancellationException) {
                debugRecorder.finishCancelled(lastChunkText)
                throw cancellationException
            } catch (exception: Exception) {
                debugRecorder.finishFailure(
                    errorMessage = exception.message ?: "Unable to generate insights.",
                    lastDisplayedText = lastChunkText,
                )
                throw exception
            }
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
