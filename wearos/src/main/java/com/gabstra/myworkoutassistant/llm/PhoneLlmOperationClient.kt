package com.gabstra.myworkoutassistant.llm

import android.content.Context
import android.util.Log
import com.gabstra.myworkoutassistant.shared.datalayer.DataLayerPaths
import com.gabstra.myworkoutassistant.shared.llm.DEFAULT_PHONE_LLM_OPERATION
import com.gabstra.myworkoutassistant.shared.llm.DEFAULT_PHONE_LLM_OPERATION_TIMEOUT_MS
import com.gabstra.myworkoutassistant.shared.llm.DEFAULT_PHONE_LLM_SYSTEM_PROMPT
import com.gabstra.myworkoutassistant.shared.llm.PhoneLlmDataMapKeys
import com.gabstra.myworkoutassistant.shared.llm.PhoneLlmOperationRequest
import com.gabstra.myworkoutassistant.shared.llm.PhoneLlmOperationResult
import com.google.android.gms.tasks.Tasks
import com.google.android.gms.wearable.CapabilityClient
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.PutDataMapRequest
import com.google.android.gms.wearable.Wearable
import com.google.gson.Gson
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit
import kotlin.coroutines.cancellation.CancellationException

class PhoneLlmOperationClient(
    context: Context,
    private val dataClient: DataClient = Wearable.getDataClient(context),
    private val gson: Gson = Gson(),
) {
    private companion object {
        const val PHONE_APP_CAPABILITY = "data_layer_app_helper_device_phone"
    }

    private val appContext = context.applicationContext

    suspend fun request(
        operation: String = DEFAULT_PHONE_LLM_OPERATION,
        title: String = operation,
        prompt: String,
        systemPrompt: String = DEFAULT_PHONE_LLM_SYSTEM_PROMPT,
        metadata: Map<String, String> = emptyMap(),
        timeoutMs: Long = DEFAULT_PHONE_LLM_OPERATION_TIMEOUT_MS,
    ): PhoneLlmOperationResult {
        return execute(
            PhoneLlmOperationRequest.create(
                requestId = UUID.randomUUID().toString(),
                operation = operation,
                title = title,
                prompt = prompt,
                systemPrompt = systemPrompt,
                metadata = metadata
            ),
            timeoutMs = timeoutMs
        )
    }

    suspend fun execute(
        request: PhoneLlmOperationRequest,
        timeoutMs: Long = DEFAULT_PHONE_LLM_OPERATION_TIMEOUT_MS,
    ): PhoneLlmOperationResult = withContext(Dispatchers.IO) {
        val requestId = request.requestId.trim().ifBlank { UUID.randomUUID().toString() }
        val operation = request.operation.trim().ifBlank { DEFAULT_PHONE_LLM_OPERATION }
        val prompt = request.prompt.trim()
        if (prompt.isBlank()) {
            return@withContext PhoneLlmOperationResult.error(
                requestId = requestId,
                operation = operation,
                errorMessage = "Missing LLM operation prompt."
            )
        }
        if (!hasReachablePhoneApp()) {
            return@withContext PhoneLlmOperationResult.error(
                requestId = requestId,
                operation = operation,
                errorMessage = "No connected phone is available for LLM operation."
            )
        }

        val normalizedRequest = request.copy(
            requestId = requestId,
            operation = operation,
            title = request.title.trim().ifBlank { operation },
            prompt = prompt,
            systemPrompt = request.systemPrompt.trim().ifBlank { DEFAULT_PHONE_LLM_SYSTEM_PROMPT }
        )
        val waiter = PhoneLlmOperationResultRegistry.registerResultWaiter(requestId)
        try {
            val requestPath = DataLayerPaths.buildPath(
                DataLayerPaths.PHONE_LLM_OPERATION_REQUEST_PREFIX,
                requestId
            )
            val putRequest = PutDataMapRequest.create(requestPath).apply {
                dataMap.putString(PhoneLlmDataMapKeys.REQUEST_ID, requestId)
                dataMap.putString(PhoneLlmDataMapKeys.REQUEST_JSON, gson.toJson(normalizedRequest))
                dataMap.putString(PhoneLlmDataMapKeys.TIMESTAMP, System.currentTimeMillis().toString())
            }.asPutDataRequest().setUrgent()

            Tasks.await(dataClient.putDataItem(putRequest), 10, TimeUnit.SECONDS)
            Log.d("PhoneLlmOperation", "Sent LLM operation request: $requestId")

            withTimeoutOrNull(timeoutMs.coerceAtLeast(1_000L)) {
                waiter.await()
            } ?: PhoneLlmOperationResult.error(
                requestId = requestId,
                operation = operation,
                errorMessage = "Timed out waiting for phone LLM operation result."
            )
        } catch (exception: CancellationException) {
            throw exception
        } catch (exception: Exception) {
            PhoneLlmOperationResult.error(
                requestId = requestId,
                operation = operation,
                errorMessage = exception.message ?: "Failed to send LLM operation request."
            )
        } finally {
            PhoneLlmOperationResultRegistry.cleanup(requestId)
        }
    }

    private fun hasReachablePhoneApp(): Boolean {
        return runCatching {
            Tasks.await(
                Wearable.getCapabilityClient(appContext).getCapability(
                    PHONE_APP_CAPABILITY,
                    CapabilityClient.FILTER_REACHABLE
                ),
                10,
                TimeUnit.SECONDS
            ).nodes.isNotEmpty()
        }.getOrElse { exception ->
            Log.w("PhoneLlmOperation", "Failed to check phone connection: ${exception.message}")
            false
        }
    }
}

object PhoneLlmOperationResultRegistry {
    private const val COMPLETED_RESULT_TTL_MS = 10 * 60 * 1_000L

    private data class CompletedResult(
        val result: PhoneLlmOperationResult,
        val receivedAtEpochMs: Long,
    )

    private val pendingResults =
        ConcurrentHashMap<String, CompletableDeferred<PhoneLlmOperationResult>>()
    private val completedResults = ConcurrentHashMap<String, CompletedResult>()

    fun registerResultWaiter(
        requestId: String,
    ): CompletableDeferred<PhoneLlmOperationResult> {
        pruneCompletedResults()
        completedResults.remove(requestId)?.let { completed ->
            return CompletableDeferred<PhoneLlmOperationResult>().apply {
                complete(completed.result)
            }
        }
        return pendingResults.compute(requestId) { _, existing ->
            when {
                existing == null -> CompletableDeferred()
                existing.isCancelled -> CompletableDeferred()
                else -> existing
            }
        } ?: CompletableDeferred()
    }

    fun completeResult(
        requestId: String,
        result: PhoneLlmOperationResult,
    ) {
        pruneCompletedResults()
        val pending = pendingResults[requestId]
        if (pending != null && !pending.isCompleted) {
            pending.complete(result)
        } else {
            completedResults[requestId] = CompletedResult(
                result = result,
                receivedAtEpochMs = System.currentTimeMillis()
            )
        }
    }

    fun cleanup(
        requestId: String,
    ) {
        pendingResults.remove(requestId)?.cancel()
        completedResults.remove(requestId)
    }

    private fun pruneCompletedResults() {
        val cutoff = System.currentTimeMillis() - COMPLETED_RESULT_TTL_MS
        completedResults.entries.removeIf { (_, completed) ->
            completed.receivedAtEpochMs < cutoff
        }
    }
}
