package com.gabstra.myworkoutassistant.llm

import android.content.Context
import com.gabstra.myworkoutassistant.MobileLlmFeatureFlags
import com.gabstra.myworkoutassistant.insights.ConfigurableWorkoutInsightsEngine
import com.gabstra.myworkoutassistant.insights.WorkoutInsightsPhase
import com.gabstra.myworkoutassistant.insights.WorkoutInsightsRequest
import com.gabstra.myworkoutassistant.shared.llm.DEFAULT_PHONE_LLM_OPERATION
import com.gabstra.myworkoutassistant.shared.llm.DEFAULT_PHONE_LLM_SYSTEM_PROMPT
import com.gabstra.myworkoutassistant.shared.llm.PhoneLlmOperationRequest
import com.gabstra.myworkoutassistant.shared.llm.PhoneLlmOperationResult
import kotlinx.coroutines.flow.collect
import kotlin.coroutines.cancellation.CancellationException

class PhoneLlmOperationExecutor(
    context: Context,
) {
    private val insightsEngine = ConfigurableWorkoutInsightsEngine(context.applicationContext)

    suspend fun execute(
        request: PhoneLlmOperationRequest,
    ): PhoneLlmOperationResult {
        val requestId = request.requestId.trim()
        val operation = request.operation.trim().ifBlank { DEFAULT_PHONE_LLM_OPERATION }
        if (!MobileLlmFeatureFlags.ENABLED) {
            return PhoneLlmOperationResult.error(
                requestId = requestId,
                operation = operation,
                errorMessage = "Phone LLM operations are temporarily disabled."
            )
        }
        val prompt = request.prompt.trim()
        if (requestId.isBlank()) {
            return PhoneLlmOperationResult.error(
                requestId = requestId,
                operation = operation,
                errorMessage = "Missing LLM operation request id."
            )
        }
        if (prompt.isBlank()) {
            return PhoneLlmOperationResult.error(
                requestId = requestId,
                operation = operation,
                errorMessage = "Missing LLM operation prompt."
            )
        }

        return try {
            var finalText = ""
            insightsEngine.generateInsights(
                WorkoutInsightsRequest(
                    title = request.title.trim().ifBlank { operation },
                    prompt = prompt,
                    systemPrompt = request.systemPrompt.trim().ifBlank {
                        DEFAULT_PHONE_LLM_SYSTEM_PROMPT
                    }
                )
            ).collect { chunk ->
                if (chunk.phase == WorkoutInsightsPhase.FINAL_SYNTHESIS && chunk.text.isNotBlank()) {
                    finalText = chunk.text
                }
            }

            if (finalText.isBlank()) {
                PhoneLlmOperationResult.error(
                    requestId = requestId,
                    operation = operation,
                    errorMessage = "No LLM output was generated."
                )
            } else {
                PhoneLlmOperationResult.success(
                    requestId = requestId,
                    operation = operation,
                    text = finalText
                )
            }
        } catch (exception: CancellationException) {
            throw exception
        } catch (exception: Exception) {
            PhoneLlmOperationResult.error(
                requestId = requestId,
                operation = operation,
                errorMessage = exception.message ?: "LLM operation failed."
            )
        }
    }
}
