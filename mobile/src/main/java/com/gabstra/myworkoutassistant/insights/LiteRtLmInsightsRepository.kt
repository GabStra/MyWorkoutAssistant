package com.gabstra.myworkoutassistant.insights

import android.content.Context
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.ensureActive
import org.json.JSONObject
import java.io.File
import kotlin.coroutines.coroutineContext

data class WorkoutInsightsChunk(
    val title: String,
    val text: String,
    val phase: WorkoutInsightsPhase,
    val statusText: String = "",
)

enum class WorkoutInsightsPhase {
    PREPARING_TOOLS,
    FETCHING_CONTEXT,
    SUMMARIZING_CONTEXT,
    CHART_ANALYSIS,
    FINAL_SYNTHESIS,
}

data class WorkoutInsightsRequest(
    val title: String,
    val prompt: String,
    val systemPrompt: String = WORKOUT_INSIGHTS_SYSTEM_PROMPT,
    val customInstructions: String = "",
    val imagePngBytes: ByteArray? = null,
    val toolContext: WorkoutInsightsToolContext? = null,
    val chartAnalysisContext: String? = null,
    val chartTimelineToolContext: WorkoutInsightsChartTimelineContext? = null,
    /**
     * When true and [toolContext] is non-null, the transport layer runs tool-calling with
     * [prompt] as the first user message instead of inlining full markdown.
     */
    val useTransportToolCalling: Boolean = false,
    /**
     * When true with non-null [toolContext], [systemPrompt] is expected to already include the compacted
     * export once; history chat can then send real multi-turn messages instead of re-inlining the export.
     */
    val historyChatSystemIncludesData: Boolean = false,
    /**
     * Ordered chat messages for history chat requests. The last message should be the current user turn.
     */
    val conversationMessages: List<HistoryChatMessage> = emptyList(),
    val debugRecorder: WorkoutInsightsDebugDumpRecorder? = null,
)

/**
 * Local transport for workout insights. All native inference runs inside the
 * isolated `:llm` process ([LlmEngineService]) through [LlmEngineGatewayClient];
 * this class keeps the public API, drives tool rounds with locally-executed
 * tools, and applies the shared generation orchestration.
 */
class LiteRtLmInsightsRepository(
    internal val context: Context,
) {
    companion object {
        const val LOG_TAG = "WorkoutInsights"
    }

    fun generateInsights(
        title: String,
        prompt: String,
    ): Flow<WorkoutInsightsChunk> = generateInsights(
        WorkoutInsightsRequest(
            title = title,
            prompt = prompt
        )
    )

    fun generateInsights(
        request: WorkoutInsightsRequest,
    ): Flow<WorkoutInsightsChunk> = flow {
        val modelPath = LiteRtLmModelStore.getConfiguredModelPath(context)
            ?: error("No LiteRT-LM model configured.")
        runWorkoutInsightsGeneration(
            request = request,
            logTag = LOG_TAG,
            transportLabel = "litert",
            emitChunk = { emit(it) },
            generateText = { transportRequest ->
                generateResponse(
                    modelPath = modelPath,
                    transportRequest = transportRequest,
                )
            },
            streamText = { transportRequest, onChunk, onProgress ->
                generateResponseStream(
                    modelPath = modelPath,
                    transportRequest = transportRequest,
                    onChunk = onChunk,
                    onProgress = onProgress,
                )
            },
            onAfterChartAnalysis = { releaseChartAnalysisResources() },
        )
    }.flowOn(Dispatchers.IO)
}

private suspend fun LiteRtLmInsightsRepository.generateResponse(
    modelPath: String,
    transportRequest: WorkoutInsightsTransportRequest,
): String {
    val accumulated = StringBuilder()
    generateResponseStream(
        modelPath = modelPath,
        transportRequest = transportRequest,
        onChunk = { chunk -> accumulated.append(chunk) },
        onProgress = { _, _ -> }
    )
    val finalText = accumulated.toString().ifBlank { "No insights were generated." }
    logWorkoutInsightsBlock(
        LiteRtLmInsightsRepository.LOG_TAG,
        transportRequest.responseLogLabel,
        finalText,
        transportRequest.debugRecorder,
    )
    return finalText
}

private suspend fun LiteRtLmInsightsRepository.generateResponseStream(
    modelPath: String,
    transportRequest: WorkoutInsightsTransportRequest,
    onChunk: suspend (String) -> Unit,
    onProgress: suspend (WorkoutInsightsPhase, String) -> Unit,
) {
    if (transportRequest.imagePngBytes != null && transportRequest.chartTimelineToolContext != null) {
        val finalText = generateChartAnalysisWithTimelineToolsResponse(
            modelPath = modelPath,
            transportRequest = transportRequest,
            onProgress = onProgress,
        )
        if (finalText.isNotBlank()) {
            onChunk(finalText)
        }
        return
    }
    if (transportRequest.imagePngBytes == null && transportRequest.toolContext != null) {
        val finalText = generateToolCallingResponse(
            modelPath = modelPath,
            transportRequest = transportRequest,
            onProgress = onProgress
        )
        if (finalText.isNotBlank()) {
            onChunk(finalText)
        }
        return
    }

    val session = createSession(modelPath, transportRequest)

    session.use {
        Log.d(
            LiteRtLmInsightsRepository.LOG_TAG,
            "${transportRequest.requestLogLabel}" +
                "_start mode=${if (transportRequest.imagePngBytes != null) "image_text" else "text_only"} prompt_chars=${transportRequest.prompt.length} image_bytes=${transportRequest.imagePngBytes?.size ?: 0}"
        )
        logWorkoutInsightsBlock(
            LiteRtLmInsightsRepository.LOG_TAG,
            "${transportRequest.requestLogLabel}_system_prompt",
            transportRequest.systemPrompt,
            transportRequest.debugRecorder,
        )
        logWorkoutInsightsBlock(
            LiteRtLmInsightsRepository.LOG_TAG,
            "${transportRequest.requestLogLabel}_user_prompt",
            transportRequest.prompt,
            transportRequest.debugRecorder,
        )
        val message = buildLlmSessionMessage(transportRequest)
        try {
            val response = it.sendMessage(message, onChunk = onChunk)
            logAssistantTurn(
                requestLogLabel = transportRequest.requestLogLabel,
                turnNumber = 1,
                response = response,
                debugRecorder = transportRequest.debugRecorder,
            )
        } finally {
            if (message is LlmSessionMessage.ImageText) {
                File(message.imagePath).delete()
            }
        }
    }
}

/**
 * Builds the session spec for the plain (non-tool-loop) paths and stages the
 * chart image into the cache directory shared with the :llm process.
 */
private suspend fun LiteRtLmInsightsRepository.createSession(
    modelPath: String,
    transportRequest: WorkoutInsightsTransportRequest,
): LlmInferenceSession {
    val initialMessages = transportRequest.conversationMessages
        .dropLast(1)
        .map { message ->
            when (message.role) {
                HistoryChatMessageRole.User -> "user" to message.content.trim()
                HistoryChatMessageRole.Assistant -> "model" to message.content.trim()
            }
        }
    return LlmEngineGatewayClient.obtain(context).createSession(
        context,
        LlmSessionSpec(
            modelPath = modelPath,
            cacheDir = context.cacheDir.absolutePath,
            backendPreference = LiteRtLmModelStore.getBackendPreference(context),
            visionEnabled = transportRequest.imagePngBytes != null,
            systemPrompt = transportRequest.systemPrompt,
            maxOutputToken = transportRequest.maxOutputTokens,
            initialMessages = initialMessages,
            toolSpecsJson = emptyList(),
        ),
    )
}

private fun LiteRtLmInsightsRepository.buildLlmSessionMessage(
    transportRequest: WorkoutInsightsTransportRequest,
): LlmSessionMessage {
    if (transportRequest.conversationMessages.isNotEmpty()) {
        val currentMessage = transportRequest.conversationMessages.last()
        require(currentMessage.role == HistoryChatMessageRole.User) {
            "History chat requests must end with a user message."
        }
        return LlmSessionMessage.User(currentMessage.content.trim())
    }
    if (transportRequest.imagePngBytes != null) {
        return LlmSessionMessage.ImageText(
            imagePath = stageImageForLlmProcess(transportRequest.imagePngBytes),
            text = transportRequest.prompt,
        )
    }
    return LlmSessionMessage.User(transportRequest.prompt)
}

private fun LiteRtLmInsightsRepository.stageImageForLlmProcess(bytes: ByteArray): String {
    val directory = File(context.cacheDir, "llm_images").apply { mkdirs() }
    return File.createTempFile("insight_", ".png", directory).apply {
        writeBytes(bytes)
    }.absolutePath
}

private suspend fun LiteRtLmInsightsRepository.generateChartAnalysisWithTimelineToolsResponse(
    modelPath: String,
    transportRequest: WorkoutInsightsTransportRequest,
    onProgress: suspend (WorkoutInsightsPhase, String) -> Unit,
): String {
    val timeline = requireNotNull(transportRequest.chartTimelineToolContext)
    val toolExecutor = WorkoutInsightsChartTimelineToolExecutor(timeline)
    val gateway = LlmEngineGatewayClient.obtain(context)

    val session = gateway.createSession(
        context,
        LlmSessionSpec(
            modelPath = modelPath,
            cacheDir = context.cacheDir.absolutePath,
            backendPreference = LiteRtLmModelStore.getBackendPreference(context),
            visionEnabled = true,
            systemPrompt = transportRequest.systemPrompt,
            maxOutputToken = transportRequest.maxOutputTokens,
            initialMessages = emptyList(),
            toolSpecsJson = toolExecutor.toolSpecsJson(),
        ),
    )
    val stagedImagePath = stageImageForLlmProcess(
        requireNotNull(transportRequest.imagePngBytes),
    )

    try {
        onProgress(WorkoutInsightsPhase.CHART_ANALYSIS, "Analyzing heart-rate chart (timeline tools)...")
        logWorkoutInsightsBlock(
            LiteRtLmInsightsRepository.LOG_TAG,
            "${transportRequest.requestLogLabel}_system_prompt",
            transportRequest.systemPrompt,
            transportRequest.debugRecorder,
        )
        logWorkoutInsightsBlock(
            LiteRtLmInsightsRepository.LOG_TAG,
            "${transportRequest.requestLogLabel}_tool_definitions",
            toolExecutor.describeToolsForLog(),
            transportRequest.debugRecorder,
        )
        logWorkoutInsightsBlock(
            LiteRtLmInsightsRepository.LOG_TAG,
            "${transportRequest.requestLogLabel}_turn_1_user_message",
            transportRequest.prompt,
            transportRequest.debugRecorder,
        )
        var response = session.sendMessage(
            LlmSessionMessage.ImageText(
                imagePath = stagedImagePath,
                text = transportRequest.prompt,
            ),
            onChunk = {},
        )
        logAssistantTurn(
            requestLogLabel = transportRequest.requestLogLabel,
            turnNumber = 1,
            response = response,
            debugRecorder = transportRequest.debugRecorder,
        )
        for (round in 0 until MAX_INSIGHTS_TOOL_ROUNDS) {
            coroutineContext.ensureActive()
            val toolCalls = when (response) {
                is LlmSessionResponse.ToolCalls -> response.calls
                is LlmSessionResponse.Text -> {
                    Log.d(
                        LiteRtLmInsightsRepository.LOG_TAG,
                        "${transportRequest.requestLogLabel}_tool_loop_exit reason=no_tool_calls turn=${round + 1}"
                    )
                    return response.text
                }
            }

            Log.d(
                LiteRtLmInsightsRepository.LOG_TAG,
                "${transportRequest.requestLogLabel}_tool_round_${round + 1}_calls=${toolCalls.joinToString { it.name }}"
            )

            val status = toolCalls.joinToString { it.name }.lowercase()
            onProgress(
                WorkoutInsightsPhase.CHART_ANALYSIS,
                "Chart analysis: $status"
            )
            val toolResponses = toolCalls.map { toolCall ->
                val arguments = JSONObject(toolCall.argumentsJson)
                logWorkoutInsightsBlock(
                    LiteRtLmInsightsRepository.LOG_TAG,
                    "${transportRequest.requestLogLabel}_tool_round_${round + 1}_${toolCall.name}_arguments",
                    renderForInsightLog(arguments),
                    transportRequest.debugRecorder,
                )
                val payload = toolExecutor.executeToJsonString(
                    name = toolCall.name,
                    arguments = arguments.toNamedMap(),
                )
                logWorkoutInsightsBlock(
                    LiteRtLmInsightsRepository.LOG_TAG,
                    "${transportRequest.requestLogLabel}_tool_round_${round + 1}_${toolCall.name}_result",
                    payload,
                    transportRequest.debugRecorder,
                )
                toolCall.name to payload
            }
            logWorkoutInsightsBlock(
                LiteRtLmInsightsRepository.LOG_TAG,
                "${transportRequest.requestLogLabel}_turn_${round + 2}_tool_message",
                toolResponses.joinToString("\n\n") { (name, payload) ->
                    "Tool: $name\nPayload:\n$payload"
                },
                transportRequest.debugRecorder,
            )

            response = session.sendMessage(
                LlmSessionMessage.ToolResponses(toolResponses),
                onChunk = {},
            )
            logAssistantTurn(
                requestLogLabel = transportRequest.requestLogLabel,
                turnNumber = round + 2,
                response = response,
                debugRecorder = transportRequest.debugRecorder,
            )
        }

        Log.d(
            LiteRtLmInsightsRepository.LOG_TAG,
            "${transportRequest.requestLogLabel}_tool_loop_exit reason=tool_budget_exhausted rounds=$MAX_INSIGHTS_TOOL_ROUNDS"
        )
        return (response as? LlmSessionResponse.Text)?.text.orEmpty()
    } finally {
        session.close()
        File(stagedImagePath).delete()
    }
}

private suspend fun LiteRtLmInsightsRepository.generateToolCallingResponse(
    modelPath: String,
    transportRequest: WorkoutInsightsTransportRequest,
    onProgress: suspend (WorkoutInsightsPhase, String) -> Unit,
): String {
    val toolContext = requireNotNull(transportRequest.toolContext)
    val toolExecutor = WorkoutInsightsToolExecutor(toolContext)
    val gateway = LlmEngineGatewayClient.obtain(context)

    val session = gateway.createSession(
        context,
        LlmSessionSpec(
            modelPath = modelPath,
            cacheDir = context.cacheDir.absolutePath,
            backendPreference = LiteRtLmModelStore.getBackendPreference(context),
            visionEnabled = false,
            systemPrompt = transportRequest.systemPrompt,
            maxOutputToken = transportRequest.maxOutputTokens,
            initialMessages = transportRequest.conversationMessages
                .dropLast(1)
                .map { message ->
                    when (message.role) {
                        HistoryChatMessageRole.User -> "user" to message.content.trim()
                        HistoryChatMessageRole.Assistant -> "model" to message.content.trim()
                    }
                },
            toolSpecsJson = toolExecutor.toolSpecsJson(),
        ),
    )

    try {
        onProgress(WorkoutInsightsPhase.PREPARING_TOOLS, "Preparing insight tools...")
        logWorkoutInsightsBlock(
            LiteRtLmInsightsRepository.LOG_TAG,
            "${transportRequest.requestLogLabel}_system_prompt",
            transportRequest.systemPrompt,
            transportRequest.debugRecorder,
        )
        logWorkoutInsightsBlock(
            LiteRtLmInsightsRepository.LOG_TAG,
            "${transportRequest.requestLogLabel}_tool_definitions",
            toolExecutor.describeToolsForLog(),
            transportRequest.debugRecorder,
        )
        logWorkoutInsightsBlock(
            LiteRtLmInsightsRepository.LOG_TAG,
            "${transportRequest.requestLogLabel}_turn_1_user_message",
            transportRequest.prompt,
            transportRequest.debugRecorder,
        )
        var response = session.sendMessage(
            buildLlmSessionMessage(transportRequest),
            onChunk = {},
        )
        logAssistantTurn(
            requestLogLabel = transportRequest.requestLogLabel,
            turnNumber = 1,
            response = response,
            debugRecorder = transportRequest.debugRecorder,
        )
        for (round in 0 until MAX_INSIGHTS_TOOL_ROUNDS) {
            coroutineContext.ensureActive()
            val toolCalls = when (response) {
                is LlmSessionResponse.ToolCalls -> response.calls
                is LlmSessionResponse.Text -> {
                    Log.d(
                        LiteRtLmInsightsRepository.LOG_TAG,
                        "${transportRequest.requestLogLabel}_tool_loop_exit reason=no_tool_calls turn=${round + 1}"
                    )
                    return response.text
                }
            }

            Log.d(
                LiteRtLmInsightsRepository.LOG_TAG,
                "${transportRequest.requestLogLabel}_tool_round_${round + 1}_calls=${toolCalls.joinToString { it.name }}"
            )

            val status = toolCalls.joinToString { it.name }.lowercase()
            onProgress(
                phaseForToolCalls(toolCalls.map { it.name }),
                "Tool round ${round + 1}: $status"
            )
            val toolResponses = toolCalls.map { toolCall ->
                val arguments = JSONObject(toolCall.argumentsJson)
                logWorkoutInsightsBlock(
                    LiteRtLmInsightsRepository.LOG_TAG,
                    "${transportRequest.requestLogLabel}_tool_round_${round + 1}_${toolCall.name}_arguments",
                    renderForInsightLog(arguments),
                    transportRequest.debugRecorder,
                )
                val payload = toolExecutor.executeToJsonString(
                    name = toolCall.name,
                    arguments = arguments.toNamedMap(),
                )
                logWorkoutInsightsBlock(
                    LiteRtLmInsightsRepository.LOG_TAG,
                    "${transportRequest.requestLogLabel}_tool_round_${round + 1}_${toolCall.name}_result",
                    payload,
                    transportRequest.debugRecorder,
                )
                toolCall.name to payload
            }
            logWorkoutInsightsBlock(
                LiteRtLmInsightsRepository.LOG_TAG,
                "${transportRequest.requestLogLabel}_turn_${round + 2}_tool_message",
                toolResponses.joinToString("\n\n") { (name, payload) ->
                    "Tool: $name\nPayload:\n$payload"
                },
                transportRequest.debugRecorder,
            )

            response = session.sendMessage(
                LlmSessionMessage.ToolResponses(toolResponses),
                onChunk = {},
            )
            logAssistantTurn(
                requestLogLabel = transportRequest.requestLogLabel,
                turnNumber = round + 2,
                response = response,
                debugRecorder = transportRequest.debugRecorder,
            )
        }

        Log.d(
            LiteRtLmInsightsRepository.LOG_TAG,
            "${transportRequest.requestLogLabel}_tool_loop_exit reason=tool_budget_exhausted rounds=$MAX_INSIGHTS_TOOL_ROUNDS"
        )
        return (response as? LlmSessionResponse.Text)?.text.orEmpty()
    } finally {
        session.close()
    }
}

private fun JSONObject.toNamedMap(): Map<String, Any?> {
    val map = mutableMapOf<String, Any?>()
    for (key in keys()) {
        map[key] = get(key)
    }
    return map
}

private suspend fun releaseChartAnalysisResources() {
    // Fire-and-forget: the :llm process releases idle (vision) engines on its
    // own schedule; this only nudges it after the memory-heavy chart path.
    Runtime.getRuntime().gc()
}

internal fun phaseForToolCalls(
    toolNames: List<String>,
): WorkoutInsightsPhase {
    return if (toolNames.any { it.contains("summarize", ignoreCase = true) }) {
        WorkoutInsightsPhase.SUMMARIZING_CONTEXT
    } else {
        WorkoutInsightsPhase.FETCHING_CONTEXT
    }
}

private fun logAssistantTurn(
    requestLogLabel: String,
    turnNumber: Int,
    text: String,
    debugRecorder: WorkoutInsightsDebugDumpRecorder? = null,
) {
    val rendered = buildString {
        append("Text:\n")
        append(text.ifBlank { "<empty>" })
    }
    logWorkoutInsightsBlock(
        LiteRtLmInsightsRepository.LOG_TAG,
        "${requestLogLabel}_turn_${turnNumber}_assistant",
        rendered,
        debugRecorder,
    )
}

private fun logAssistantTurn(
    requestLogLabel: String,
    turnNumber: Int,
    response: LlmSessionResponse,
    debugRecorder: WorkoutInsightsDebugDumpRecorder? = null,
) {
    val rendered = when (response) {
        is LlmSessionResponse.Text -> buildString {
            append("Text:\n")
            append(response.text.ifBlank { "<empty>" })
        }
        is LlmSessionResponse.ToolCalls -> buildString {
            append("Tool calls:\n")
            append(
                response.calls.joinToString("\n\n") { toolCall ->
                    buildString {
                        append("Tool: ")
                        append(toolCall.name)
                        append("\nArguments:\n")
                        append(renderForInsightLog(runCatching { JSONObject(toolCall.argumentsJson) }.getOrNull()))
                    }
                }
            )
        }
    }
    logWorkoutInsightsBlock(
        LiteRtLmInsightsRepository.LOG_TAG,
        "${requestLogLabel}_turn_${turnNumber}_assistant",
        rendered,
        debugRecorder,
    )
}
