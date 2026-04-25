package com.gabstra.myworkoutassistant.insights

import android.content.Context
import android.util.Base64
import android.util.Log
import com.openai.client.okhttp.OpenAIOkHttpClient
import com.openai.core.http.StreamResponse
import com.openai.models.chat.completions.ChatCompletionChunk
import com.openai.models.chat.completions.ChatCompletionContentPart
import com.openai.models.chat.completions.ChatCompletionContentPartImage
import com.openai.models.chat.completions.ChatCompletionContentPartText
import com.openai.models.chat.completions.ChatCompletionCreateParams
import com.openai.models.chat.completions.ChatCompletionFunctionTool
import com.openai.models.chat.completions.ChatCompletionMessageFunctionToolCall
import com.openai.models.chat.completions.ChatCompletionMessageParam
import com.openai.models.chat.completions.ChatCompletionMessageToolCall
import com.openai.models.chat.completions.ChatCompletionToolMessageParam
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
            "Remote insights are not configured. Set the base URL, API key, and model in Settings."
        }
        runWorkoutInsightsGeneration(
            request = request,
            logTag = LiteRtLmInsightsRepository.LOG_TAG,
            transportLabel = "remote",
            emitChunk = { emit(it) },
            generateText = { transportRequest ->
                generateResponse(
                    config = config,
                    transportRequest = transportRequest,
                )
            },
            streamText = { transportRequest, onChunk, onProgress ->
                generateResponseStream(
                    config = config,
                    transportRequest = transportRequest,
                    onChunk = onChunk,
                    onProgress = onProgress,
                )
            },
        )
    }.flowOn(Dispatchers.IO)

    private suspend fun generateResponse(
        config: RemoteOpenAiConfig,
        transportRequest: WorkoutInsightsTransportRequest,
    ): String {
        val accumulated = StringBuilder()
        generateResponseStream(
            config = config,
            transportRequest = transportRequest,
            onChunk = { chunk -> accumulated.append(chunk) },
            onProgress = { _, _ -> },
        )
        val finalText = accumulated.toString().ifBlank { "No insights were generated." }
        logWorkoutInsightsBlock(
            LiteRtLmInsightsRepository.LOG_TAG,
            transportRequest.responseLogLabel,
            finalText
        )
        return finalText
    }

    private suspend fun generateResponseStream(
        config: RemoteOpenAiConfig,
        transportRequest: WorkoutInsightsTransportRequest,
        onChunk: suspend (String) -> Unit,
        onProgress: suspend (WorkoutInsightsPhase, String) -> Unit,
    ) {
        if (transportRequest.imagePngBytes != null && transportRequest.chartTimelineToolContext != null) {
            val finalText = generateChartAnalysisWithTimelineToolsResponse(
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
                config = config,
                transportRequest = transportRequest,
                onProgress = onProgress,
            )
            if (finalText.isNotBlank()) {
                onChunk(finalText)
            }
            return
        }

        val client = OpenAIOkHttpClient.builder()
            .apiKey(config.apiKey.trim())
            .baseUrl(normalizeBaseUrl(config.baseUrl))
            .build()

        Log.d(
            LiteRtLmInsightsRepository.LOG_TAG,
            "${transportRequest.requestLogLabel}" +
                "_start mode=${if (transportRequest.imagePngBytes != null) "image_text" else "text_only"} endpoint=${config.baseUrl.trim()} prompt_chars=${transportRequest.prompt.length} image_bytes=${transportRequest.imagePngBytes?.size ?: 0}"
        )
        logWorkoutInsightsBlock(
            LiteRtLmInsightsRepository.LOG_TAG,
            "${transportRequest.requestLogLabel}_system_prompt",
            transportRequest.systemPrompt
        )
        logWorkoutInsightsBlock(
            LiteRtLmInsightsRepository.LOG_TAG,
            "${transportRequest.requestLogLabel}_user_prompt",
            transportRequest.prompt
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
        config: RemoteOpenAiConfig,
        transportRequest: WorkoutInsightsTransportRequest,
        onProgress: suspend (WorkoutInsightsPhase, String) -> Unit,
    ): String {
        val client = OpenAIOkHttpClient.builder()
            .apiKey(config.apiKey.trim())
            .baseUrl(normalizeBaseUrl(config.baseUrl))
            .build()
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
        logWorkoutInsightsBlock(
            LiteRtLmInsightsRepository.LOG_TAG,
            "${transportRequest.requestLogLabel}_system_prompt",
            transportRequest.systemPrompt
        )
        logWorkoutInsightsBlock(
            LiteRtLmInsightsRepository.LOG_TAG,
            "${transportRequest.requestLogLabel}_tool_definitions",
            toolExecutor.describeToolsForLog()
        )
        logWorkoutInsightsBlock(
            LiteRtLmInsightsRepository.LOG_TAG,
            "${transportRequest.requestLogLabel}_turn_1_user_message",
            transportRequest.prompt
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
                    renderForInsightLog(arguments)
                )
                val result = toolExecutor.executeToJsonString(
                    name = functionCall.function().name(),
                    arguments = arguments
                )
                logWorkoutInsightsBlock(
                    LiteRtLmInsightsRepository.LOG_TAG,
                    "${transportRequest.requestLogLabel}_tool_round_${round + 1}_${functionCall.function().name()}_result",
                    result
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
        config: RemoteOpenAiConfig,
        transportRequest: WorkoutInsightsTransportRequest,
        onProgress: suspend (WorkoutInsightsPhase, String) -> Unit,
    ): String {
        val client = OpenAIOkHttpClient.builder()
            .apiKey(config.apiKey.trim())
            .baseUrl(normalizeBaseUrl(config.baseUrl))
            .build()
        val toolExecutor = WorkoutInsightsToolExecutor(requireNotNull(transportRequest.toolContext))
        val messages = mutableListOf<ChatCompletionMessageParam>()

        messages.addAll(
            ChatCompletionCreateParams.builder()
                .addSystemMessage(transportRequest.systemPrompt)
                .addUserMessage(transportRequest.prompt)
                .build()
                .messages()
        )

        onProgress(WorkoutInsightsPhase.PREPARING_TOOLS, "Preparing insight tools...")
        logWorkoutInsightsBlock(
            LiteRtLmInsightsRepository.LOG_TAG,
            "${transportRequest.requestLogLabel}_system_prompt",
            transportRequest.systemPrompt
        )
        logWorkoutInsightsBlock(
            LiteRtLmInsightsRepository.LOG_TAG,
            "${transportRequest.requestLogLabel}_tool_definitions",
            toolExecutor.describeToolsForLog()
        )
        logWorkoutInsightsBlock(
            LiteRtLmInsightsRepository.LOG_TAG,
            "${transportRequest.requestLogLabel}_turn_1_user_message",
            transportRequest.prompt
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
                "Tool round ${round + 1}: ${toolCalls.joinToString { it.toolName() }.lowercase()}"
            )

            messages.add(ChatCompletionMessageParam.ofAssistant(message.toParam()))
            toolCalls.forEach { toolCall ->
                val functionCall = toolCall.asFunction()
                val arguments = parseToolArguments(functionCall)
                logWorkoutInsightsBlock(
                    LiteRtLmInsightsRepository.LOG_TAG,
                    "${transportRequest.requestLogLabel}_tool_round_${round + 1}_${functionCall.function().name()}_arguments",
                    renderForInsightLog(arguments)
                )
                val result = toolExecutor.executeToJsonString(
                    name = functionCall.function().name(),
                    arguments = arguments
                )
                logWorkoutInsightsBlock(
                    LiteRtLmInsightsRepository.LOG_TAG,
                    "${transportRequest.requestLogLabel}_tool_round_${round + 1}_${functionCall.function().name()}_result",
                    result
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
                .model(config.model.trim())
                .addSystemMessage(transportRequest.systemPrompt),
            transportRequest,
        )

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
        val chunkIterator = streamResponse.stream().iterator()
        while (chunkIterator.hasNext()) {
            val chunk = chunkIterator.next()
            for (choice in chunk.choices()) {
                val contentDelta = choice.delta().content().orElse(null)
                if (!contentDelta.isNullOrBlank()) {
                    onChunk(contentDelta)
                }
            }
        }
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
            rendered
        )
    }
}
