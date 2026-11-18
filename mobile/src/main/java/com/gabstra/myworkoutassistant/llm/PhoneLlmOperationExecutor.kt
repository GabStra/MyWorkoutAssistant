package com.gabstra.myworkoutassistant.llm

import android.content.Context
import com.gabstra.myworkoutassistant.R
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
    private val appContext = context.applicationContext
    private val insightsEngine = ConfigurableWorkoutInsightsEngine(appContext)

    suspend fun execute(
        request: PhoneLlmOperationRequest,
    ): PhoneLlmOperationResult {
        val requestId = request.requestId.trim()
        val operation = request.operation.trim().ifBlank { DEFAULT_PHONE_LLM_OPERATION }
        if (!MobileLlmFeatureFlags.isEnabled(appContext)) {
            return PhoneLlmOperationResult.error(
                requestId = requestId,
                operation = operation,
                errorMessage = appContext.getString(R.string.loc_phone_llm_disabled)
            )
        }
        val prompt = request.prompt.trim()
        if (requestId.isBlank()) {
            return PhoneLlmOperationResult.error(
                requestId = requestId,
                operation = operation,
                errorMessage = appContext.getString(R.string.loc_phone_llm_missing_request_id)
            )
        }
        if (prompt.isBlank()) {
            return PhoneLlmOperationResult.error(
                requestId = requestId,
                operation = operation,
                errorMessage = appContext.getString(R.string.loc_phone_llm_missing_prompt)
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
                    errorMessage = appContext.getString(R.string.loc_phone_llm_no_output)
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
                errorMessage = exception.message ?: appContext.getString(R.string.loc_phone_llm_failed)
            )
        }
    }
}
