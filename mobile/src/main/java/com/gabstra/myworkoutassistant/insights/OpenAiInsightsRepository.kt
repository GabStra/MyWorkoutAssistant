package com.gabstra.myworkoutassistant.insights

import android.content.Context
import android.util.Base64
import android.util.Log
import com.openai.client.okhttp.OpenAIOkHttpClient
import com.openai.client.OpenAIClient
import com.openai.core.http.StreamResponse
import com.openai.models.chat.completions.ChatCompletionChunk
import com.openai.models.chat.completions.ChatCompletionAssistantMessageParam
import com.openai.models.chat.completions.ChatCompletionContentPart
import com.openai.models.chat.completions.ChatCompletionContentPartImage
import com.openai.models.chat.completions.ChatCompletionContentPartText
import com.openai.models.chat.completions.ChatCompletionCreateParams
import com.openai.models.chat.completions.ChatCompletionFunctionTool
import com.openai.models.chat.completions.ChatCompletionMessageFunctionToolCall
import com.openai.models.chat.completions.ChatCompletionMessageParam
import com.openai.models.chat.completions.ChatCompletionMessageToolCall
import com.openai.models.chat.completions.ChatCompletionToolMessageParam
import com.openai.models.chat.completions.ChatCompletionUserMessageParam
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.flow.Flow
import kotlin.coroutines.coroutineContext
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import org.json.JSONObject

class OpenAiInsightsRepository(
    private val context: Context,
) : WorkoutInsightsEngine {
    override fun generateInsights(
        request: WorkoutInsightsRequest,
    ): Flow<WorkoutInsightsChunk> = flow {
        val config = WorkoutInsightsSettingsStore.getRemoteConfig(context)
        require(config.isComplete()) {
            "Remote insights are not configured. Set the base URL and model in Settings."
        }
        val client = createClient(config)
        runWorkoutInsightsGeneration(
            request = request,
            logTag = LiteRtLmInsightsRepository.LOG_TAG,
            transportLabel = "remote",
            emitChunk = { emit(it) },
            generateText = { transportRequest ->
                generateResponse(
                    client = client,
                    config = config,
                    transportRequest = transportRequest,
                )
            },
            streamText = { transportRequest, onChunk, onProgress ->
                generateResponseStream(
                    client = client,
                    config = config,
                    transportRequest = transportRequest,
                    onChunk = onChunk,
                    onProgress = onProgress,
                )
            },
        )
    }.flowOn(Dispatchers.IO)

    private fun createClient(config: RemoteOpenAiConfig): OpenAIClient {
        return OpenAIOkHttpClient.builder()
            .apiKey(config.apiKey.trim().ifBlank { REMOTE_OPENAI_KEY_PLACEHOLDER })
            .baseUrl(normalizeBaseUrl(config.baseUrl))
            .build()
    }

    private suspend fun generateResponse(
        client: OpenAIClient,
        config: RemoteOpenAiConfig,
        transportRequest: WorkoutInsightsTransportRequest,
    ): String {
        val accumulated = StringBuilder()
        generateResponseStream(
            client = client,
            config = config,
            transportRequest = transportRequest,
            onChunk = { chunk -> accumulated.append(chunk) },
            onProgress = { _, _ -> },
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

    private suspend fun generateResponseStream(
        client: OpenAIClient,
        config: RemoteOpenAiConfig,
        transportRequest: WorkoutInsightsTransportRequest,
        onChunk: suspend (String) -> Unit,
        onProgress: suspend (WorkoutInsightsPhase, String) -> Unit,
    ) {
        if (transportRequest.imagePngBytes != null && transportRequest.chartTimelineToolContext != null) {
            val finalText = generateChartAnalysisWithTimelineToolsResponse(
                client = client,
                config = config,
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
                client = client,
                config = config,
                transportRequest = transportRequest,
                onProgress = onProgress,
            )
            if (finalText.isNotBlank()) {
                onChunk(finalText)
            }
            return
        }

        Log.d(
            LiteRtLmInsightsRepository.LOG_TAG,
            "${transportRequest.requestLogLabel}" +
                "_start mode=${if (transportRequest.imagePngBytes != null) "image_text" else "text_only"} endpoint=${config.baseUrl.trim()} prompt_chars=${transportRequest.prompt.length} image_bytes=${transportRequest.imagePngBytes?.size ?: 0}"
        )
        transportRequest.debugRecorder?.recordTransportRequest(
            transportRequest = transportRequest,
            backendMetadata = mapOf(
                "base_url" to config.baseUrl.trim(),
                "model" to config.model.trim(),
                "mode" to if (transportRequest.imagePngBytes != null) "image_text" else "text_only",
            ),
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

        val params = buildChatCompletionParams(
            config = config,
            transportRequest = transportRequest,
        )

        client.chat().completions().createStreaming(params).use { streamResponse ->
            consumeChatCompletionStream(streamResponse, onChunk)
        }
    }

    private suspend fun generateChartAnalysisWithTimelineToolsResponse(
        client: OpenAIClient,
        config: RemoteOpenAiConfig,
        transportRequest: WorkoutInsightsTransportRequest,
        onProgress: suspend (WorkoutInsightsPhase, String) -> Unit,
    ): String {
        val toolExecutor = WorkoutInsightsChartTimelineToolExecutor(
            requireNotNull(transportRequest.chartTimelineToolContext)
        )
        val messages = mutableListOf<ChatCompletionMessageParam>()
        val imageDataUrl =
            "data:image/png;base64," + Base64.encodeToString(
                requireNotNull(transportRequest.imagePngBytes),
                Base64.NO_WRAP
            )
        messages.addAll(
            ChatCompletionCreateParams.builder()
                .addSystemMessage(transportRequest.systemPrompt)
                .addUserMessageOfArrayOfContentParts(
                    listOf(
                        ChatCompletionContentPart.ofText(
                            ChatCompletionContentPartText.builder()
                                .text(transportRequest.prompt)
                                .build()
                        ),
                        ChatCompletionContentPart.ofImageUrl(
                            ChatCompletionContentPartImage.builder()
                                .imageUrl(
                                    ChatCompletionContentPartImage.ImageUrl.builder()
                                        .url(imageDataUrl)
                                        .build()
                                )
                                .build()
                        ),
                    )
                )
                .build()
                .messages()
        )

        onProgress(WorkoutInsightsPhase.CHART_ANALYSIS, "Analyzing heart-rate chart (timeline tools)...")
        transportRequest.debugRecorder?.recordTransportRequest(
            transportRequest = transportRequest,
            backendMetadata = mapOf(
                "base_url" to config.baseUrl.trim(),
                "model" to config.model.trim(),
                "mode" to "image_text_tool_loop",
            ),
        )
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

        for (round in 0 until MAX_INSIGHTS_TOOL_ROUNDS) {
            coroutineContext.ensureActive()
            val builder = applyMaxOutputTokensIfSet(
                ChatCompletionCreateParams.builder()
                    .model(config.model.trim())
                    .messages(messages)
                    .parallelToolCalls(false),
                transportRequest,
            )

            toolExecutor.openAiFunctionDefinitions().forEach { definition ->
                builder.addTool(ChatCompletionFunctionTool.builder().function(definition).build())
            }

            val completion = client.chat().completions().create(builder.build())
            val message = completion.choices().firstOrNull()?.message()
                ?: return "No insights were generated."
            val assistantContent = message.content().orElse("<empty>")
            val toolCalls = message.toolCalls().orElse(emptyList())
            logOpenAiAssistantMessage(
                requestLogLabel = transportRequest.requestLogLabel,
                turnNumber = round + 1,
                assistantContent = assistantContent,
                toolCalls = toolCalls,
                debugRecorder = transportRequest.debugRecorder,
            )

            if (toolCalls.isEmpty()) {
                Log.d(
                    LiteRtLmInsightsRepository.LOG_TAG,
                    "${transportRequest.requestLogLabel}_tool_loop_exit reason=no_tool_calls turn=${round + 1}"
                )
                return assistantContent.ifBlank { "No insights were generated." }
            }

            Log.d(
                LiteRtLmInsightsRepository.LOG_TAG,
                "${transportRequest.requestLogLabel}_tool_round_${round + 1}_calls=${toolCalls.joinToString { it.toolName() }}"
            )
            onProgress(
                WorkoutInsightsPhase.CHART_ANALYSIS,
                "Chart analysis: ${toolCalls.joinToString { it.toolName() }.lowercase()}"
            )

            messages.add(ChatCompletionMessageParam.ofAssistant(message.toParam()))
            toolCalls.forEach { toolCall ->
                val functionCall = toolCall.asFunction()
                val arguments = parseToolArguments(functionCall)
                logWorkoutInsightsBlock(
                    LiteRtLmInsightsRepository.LOG_TAG,
                    "${transportRequest.requestLogLabel}_tool_round_${round + 1}_${functionCall.function().name()}_arguments",
                    renderForInsightLog(arguments),
                    transportRequest.debugRecorder,
                )
                val result = toolExecutor.executeToJsonString(
                    name = functionCall.function().name(),
                    arguments = arguments
                )
                logWorkoutInsightsBlock(
                    LiteRtLmInsightsRepository.LOG_TAG,
                    "${transportRequest.requestLogLabel}_tool_round_${round + 1}_${functionCall.function().name()}_result",
                    result,
                    transportRequest.debugRecorder,
                )
                messages.add(
                    ChatCompletionMessageParam.ofTool(
                        ChatCompletionToolMessageParam.builder()
                            .toolCallId(functionCall.id())
                            .content(result)
                            .build()
                    )
                )
            }
        }

        Log.d(
            LiteRtLmInsightsRepository.LOG_TAG,
            "${transportRequest.requestLogLabel}_tool_loop_exit reason=tool_budget_exhausted rounds=$MAX_INSIGHTS_TOOL_ROUNDS"
        )
        return "Unable to complete chart analysis within the configured tool-call budget."
    }

    private suspend fun generateToolCallingResponse(
        client: OpenAIClient,
        config: RemoteOpenAiConfig,
        transportRequest: WorkoutInsightsTransportRequest,
        onProgress: suspend (WorkoutInsightsPhase, String) -> Unit,
    ): String {
        val toolExecutor = WorkoutInsightsToolExecutor(requireNotNull(transportRequest.toolContext))
        val messages = mutableListOf<ChatCompletionMessageParam>()

        messages.addAll(
            ChatCompletionCreateParams.builder()
                .addSystemMessage(transportRequest.systemPrompt)
                .build()
                .messages()
        )
        if (transportRequest.conversationMessages.isNotEmpty()) {
            messages.addAll(
                transportRequest.conversationMessages.map { message ->
                    when (message.role) {
                        HistoryChatMessageRole.User ->
                            ChatCompletionMessageParam.ofUser(
                                ChatCompletionUserMessageParam.builder()
                                    .content(message.content.trim())
                                    .build()
                            )
                        HistoryChatMessageRole.Assistant ->
                            ChatCompletionMessageParam.ofAssistant(
                                ChatCompletionAssistantMessageParam.builder()
                                    .content(message.content.trim())
                                    .build()
                            )
                    }
                }
            )
        } else {
            messages.add(
                ChatCompletionCreateParams.builder()
                    .addUserMessage(transportRequest.prompt)
                    .build()
                    .messages()
                    .last()
            )
        }

        onProgress(WorkoutInsightsPhase.PREPARING_TOOLS, "Preparing insight tools...")
        transportRequest.debugRecorder?.recordTransportRequest(
            transportRequest = transportRequest,
            backendMetadata = mapOf(
                "base_url" to config.baseUrl.trim(),
                "model" to config.model.trim(),
                "mode" to "text_tool_loop",
            ),
        )
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
        for (round in 0 until MAX_INSIGHTS_TOOL_ROUNDS) {
            coroutineContext.ensureActive()
            val builder = applyMaxOutputTokensIfSet(
                ChatCompletionCreateParams.builder()
                    .model(config.model.trim())
                    .messages(messages)
                    .parallelToolCalls(false),
                transportRequest,
            )

            toolExecutor.openAiFunctionDefinitions().forEach { definition ->
                builder.addTool(ChatCompletionFunctionTool.builder().function(definition).build())
            }

            val completion = client.chat().completions().create(builder.build())
            val message = completion.choices().firstOrNull()?.message()
                ?: return "No insights were generated."
            val assistantContent = message.content().orElse("<empty>")
            val toolCalls = message.toolCalls().orElse(emptyList())
            logOpenAiAssistantMessage(
                requestLogLabel = transportRequest.requestLogLabel,
                turnNumber = round + 1,
                assistantContent = assistantContent,
                toolCalls = toolCalls,
                debugRecorder = transportRequest.debugRecorder,
            )

            if (toolCalls.isEmpty()) {
                Log.d(
                    LiteRtLmInsightsRepository.LOG_TAG,
                    "${transportRequest.requestLogLabel}_tool_loop_exit reason=no_tool_calls turn=${round + 1}"
                )
                return assistantContent.ifBlank { "No insights were generated." }
            }

            Log.d(
                LiteRtLmInsightsRepository.LOG_TAG,
                "${transportRequest.requestLogLabel}_tool_round_${round + 1}_calls=${toolCalls.joinToString { it.toolName() }}"
            )
            onProgress(
                phaseForToolCalls(toolCalls.map { it.toolName() }),
                "Reading your workout data (step ${round + 1})..."
            )

            messages.add(ChatCompletionMessageParam.ofAssistant(message.toParam()))
            toolCalls.forEach { toolCall ->
                val functionCall = toolCall.asFunction()
                val arguments = parseToolArguments(functionCall)
                logWorkoutInsightsBlock(
                    LiteRtLmInsightsRepository.LOG_TAG,
                    "${transportRequest.requestLogLabel}_tool_round_${round + 1}_${functionCall.function().name()}_arguments",
                    renderForInsightLog(arguments),
                    transportRequest.debugRecorder,
                )
                val result = toolExecutor.executeToJsonString(
                    name = functionCall.function().name(),
                    arguments = arguments
                )
                logWorkoutInsightsBlock(
                    LiteRtLmInsightsRepository.LOG_TAG,
                    "${transportRequest.requestLogLabel}_tool_round_${round + 1}_${functionCall.function().name()}_result",
                    result,
                    transportRequest.debugRecorder,
                )
                messages.add(
                    ChatCompletionMessageParam.ofTool(
                        ChatCompletionToolMessageParam.builder()
                            .toolCallId(functionCall.id())
                            .content(result)
                            .build()
                    )
                )
            }
        }

        Log.d(
            LiteRtLmInsightsRepository.LOG_TAG,
            "${transportRequest.requestLogLabel}_tool_loop_exit reason=tool_budget_exhausted rounds=$MAX_INSIGHTS_TOOL_ROUNDS"
        )
        return "Unable to complete tool-driven insight synthesis within the configured tool-call budget."
    }

    private fun buildChatCompletionParams(
        config: RemoteOpenAiConfig,
        transportRequest: WorkoutInsightsTransportRequest,
    ): ChatCompletionCreateParams {
        val builder = applyMaxOutputTokensIfSet(
            ChatCompletionCreateParams.builder()
                .model(config.model.trim()),
            transportRequest,
        )

        if (transportRequest.conversationMessages.isNotEmpty()) {
            val messages = mutableListOf<ChatCompletionMessageParam>()
            messages.addAll(
                ChatCompletionCreateParams.builder()
                    .addSystemMessage(transportRequest.systemPrompt)
                    .build()
                    .messages()
            )
            messages.addAll(
                transportRequest.conversationMessages.map { message ->
                    when (message.role) {
                        HistoryChatMessageRole.User ->
                            ChatCompletionMessageParam.ofUser(
                                ChatCompletionUserMessageParam.builder()
                                    .content(message.content.trim())
                                    .build()
                            )
                        HistoryChatMessageRole.Assistant ->
                            ChatCompletionMessageParam.ofAssistant(
                                ChatCompletionAssistantMessageParam.builder()
                                    .content(message.content.trim())
                                    .build()
                            )
                    }
                }
            )
            builder.messages(messages)
            return builder.build()
        }

        builder.addSystemMessage(transportRequest.systemPrompt)

        if (transportRequest.imagePngBytes != null) {
            val imageDataUrl = "data:image/png;base64," + Base64.encodeToString(transportRequest.imagePngBytes, Base64.NO_WRAP)
            builder.addUserMessageOfArrayOfContentParts(
                listOf(
                    ChatCompletionContentPart.ofText(
                        ChatCompletionContentPartText.builder()
                            .text(transportRequest.prompt)
                            .build()
                    ),
                    ChatCompletionContentPart.ofImageUrl(
                        ChatCompletionContentPartImage.builder()
                            .imageUrl(
                                ChatCompletionContentPartImage.ImageUrl.builder()
                                    .url(imageDataUrl)
                                    .build()
                            )
                            .build()
                    ),
                )
            )
        } else {
            builder.addUserMessage(transportRequest.prompt)
        }

        return builder.build()
    }

    private suspend fun consumeChatCompletionStream(
        streamResponse: StreamResponse<ChatCompletionChunk>,
        onChunk: suspend (String) -> Unit,
    ) {
        collectChatCompletionContent(streamResponse.stream().iterator(), onChunk)
    }

    private fun normalizeBaseUrl(
        baseUrl: String,
    ): String {
        val trimmed = baseUrl.trim().trimEnd('/')
        return if (trimmed.endsWith("/v1", ignoreCase = true)) trimmed else "$trimmed/v1"
    }

    private fun applyMaxOutputTokensIfSet(
        builder: ChatCompletionCreateParams.Builder,
        transportRequest: WorkoutInsightsTransportRequest,
    ): ChatCompletionCreateParams.Builder {
        transportRequest.maxOutputTokens?.let { cap ->
            builder.maxCompletionTokens(cap.toLong())
        }
        return builder
    }

    private fun ChatCompletionMessageToolCall.toolName(): String {
        return if (isFunction()) {
            asFunction().function().name()
        } else {
            "custom"
        }
    }

    private fun parseToolArguments(
        toolCall: ChatCompletionMessageFunctionToolCall,
    ): Map<String, Any?> {
        val rawArguments = toolCall.function().arguments()
        return if (rawArguments.isBlank()) {
            emptyMap()
        } else {
            jsonObjectToMap(JSONObject(rawArguments))
        }
    }

    private fun logOpenAiAssistantMessage(
        requestLogLabel: String,
        turnNumber: Int,
        assistantContent: String,
        toolCalls: List<ChatCompletionMessageToolCall>,
        debugRecorder: WorkoutInsightsDebugDumpRecorder? = null,
    ) {
        val rendered = buildString {
            append("Text:\n")
            append(assistantContent)
            if (toolCalls.isNotEmpty()) {
                append("\n\nTool calls:\n")
                append(
                    toolCalls.joinToString("\n\n") { toolCall ->
                        val functionCall = toolCall.asFunction()
                        buildString {
                            append("Tool: ")
                            append(functionCall.function().name())
                            append("\nArguments:\n")
                            append(functionCall.function().arguments().ifBlank { "{}" })
                        }
                    }
                )
            }
        }
        logWorkoutInsightsBlock(
            LiteRtLmInsightsRepository.LOG_TAG,
            "${requestLogLabel}_turn_${turnNumber}_assistant_message",
            rendered,
            debugRecorder,
        )
    }
}

/** Sent when the user leaves the API key empty; unauthenticated servers ignore it, hosted ones reject it with a clear 401. */
private const val REMOTE_OPENAI_KEY_PLACEHOLDER = "none"

/**
 * Streams content deltas to [onChunk]. Some OpenAI-compatible servers emit one
 * token per chunk, so whitespace-only deltas (newlines, spaces) are significant
 * markdown content and must be kept; only null or empty content is skipped.
 */
internal suspend fun collectChatCompletionContent(
    chunks: Iterator<ChatCompletionChunk>,
    onChunk: suspend (String) -> Unit,
) {
    while (chunks.hasNext()) {
        val chunk = chunks.next()
        for (choice in chunk.choices()) {
            val contentDelta = choice.delta().content().orElse(null)
            if (!contentDelta.isNullOrEmpty()) {
                onChunk(contentDelta)
            }
        }
    }
}
