package com.gabstra.myworkoutassistant.shared.llm

const val DEFAULT_PHONE_LLM_OPERATION = "generic"
const val DEFAULT_PHONE_LLM_OPERATION_TIMEOUT_MS = 300_000L
const val DEFAULT_PHONE_LLM_SYSTEM_PROMPT =
    "You are assisting inside MyWorkoutAssistant. Follow the requested operation and return only the useful result."

object PhoneLlmDataMapKeys {
    const val REQUEST_ID = "requestId"
    const val REQUEST_JSON = "requestJson"
    const val RESULT_JSON = "resultJson"
    const val TIMESTAMP = "timestamp"
}

data class PhoneLlmOperationRequest(
    val requestId: String,
    val operation: String,
    val title: String,
    val prompt: String,
    val systemPrompt: String = DEFAULT_PHONE_LLM_SYSTEM_PROMPT,
    val metadata: Map<String, String> = emptyMap(),
) {
    companion object {
        fun create(
            requestId: String,
            operation: String = DEFAULT_PHONE_LLM_OPERATION,
            title: String = operation,
            prompt: String,
            systemPrompt: String = DEFAULT_PHONE_LLM_SYSTEM_PROMPT,
            metadata: Map<String, String> = emptyMap(),
        ): PhoneLlmOperationRequest {
            val normalizedOperation = operation.trim().ifBlank { DEFAULT_PHONE_LLM_OPERATION }
            return PhoneLlmOperationRequest(
                requestId = requestId.trim(),
                operation = normalizedOperation,
                title = title.trim().ifBlank { normalizedOperation },
                prompt = prompt,
                systemPrompt = systemPrompt.trim().ifBlank { DEFAULT_PHONE_LLM_SYSTEM_PROMPT },
                metadata = metadata
            )
        }
    }
}

enum class PhoneLlmOperationStatus {
    SUCCESS,
    ERROR,
}

data class PhoneLlmOperationResult(
    val requestId: String,
    val operation: String,
    val status: PhoneLlmOperationStatus,
    val text: String? = null,
    val errorMessage: String? = null,
    val completedAtEpochMs: Long = System.currentTimeMillis(),
) {
    val isSuccess: Boolean
        get() = status == PhoneLlmOperationStatus.SUCCESS

    companion object {
        fun success(
            requestId: String,
            operation: String,
            text: String,
        ): PhoneLlmOperationResult = PhoneLlmOperationResult(
            requestId = requestId,
            operation = operation,
            status = PhoneLlmOperationStatus.SUCCESS,
            text = text
        )

        fun error(
            requestId: String,
            operation: String,
            errorMessage: String,
        ): PhoneLlmOperationResult = PhoneLlmOperationResult(
            requestId = requestId,
            operation = operation,
            status = PhoneLlmOperationStatus.ERROR,
            errorMessage = errorMessage
        )
    }
}
