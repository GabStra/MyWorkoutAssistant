package com.gabstra.myworkoutassistant.shared.llm

import com.gabstra.myworkoutassistant.shared.datalayer.DataLayerPaths
import com.google.gson.Gson
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PhoneLlmOperationContractTest {
    private val gson = Gson()

    @Test
    fun create_normalizesBlankOperationTitleAndSystemPrompt() {
        val request = PhoneLlmOperationRequest.create(
            requestId = " request-1 ",
            operation = " ",
            title = " ",
            prompt = "Summarize this set.",
            systemPrompt = " "
        )

        assertEquals("request-1", request.requestId)
        assertEquals(DEFAULT_PHONE_LLM_OPERATION, request.operation)
        assertEquals(DEFAULT_PHONE_LLM_OPERATION, request.title)
        assertEquals(DEFAULT_PHONE_LLM_SYSTEM_PROMPT, request.systemPrompt)
    }

    @Test
    fun requestAndResult_roundTripThroughGson() {
        val request = PhoneLlmOperationRequest.create(
            requestId = "request-2",
            operation = "summarize_workout",
            title = "Summarize workout",
            prompt = "Summarize the latest workout.",
            metadata = mapOf("source" to "wear")
        )
        val result = PhoneLlmOperationResult.success(
            requestId = request.requestId,
            operation = request.operation,
            text = "Use a lighter next warm-up jump."
        )

        val parsedRequest = gson.fromJson(
            gson.toJson(request),
            PhoneLlmOperationRequest::class.java
        )
        val parsedResult = gson.fromJson(
            gson.toJson(result),
            PhoneLlmOperationResult::class.java
        )

        assertEquals(request, parsedRequest)
        assertEquals(result, parsedResult)
        assertTrue(parsedResult.isSuccess)
    }

    @Test
    fun phoneLlmPaths_areTransactionScoped() {
        val requestPath = DataLayerPaths.buildPath(
            DataLayerPaths.PHONE_LLM_OPERATION_REQUEST_PREFIX,
            "request-3"
        )
        val resultPath = DataLayerPaths.buildPath(
            DataLayerPaths.PHONE_LLM_OPERATION_RESULT_PREFIX,
            "request-3"
        )

        assertEquals(
            "request-3",
            DataLayerPaths.parseTransactionId(
                requestPath,
                DataLayerPaths.PHONE_LLM_OPERATION_REQUEST_PREFIX
            )
        )
        assertEquals(
            "request-3",
            DataLayerPaths.parseTransactionId(
                resultPath,
                DataLayerPaths.PHONE_LLM_OPERATION_RESULT_PREFIX
            )
        )
    }
}
