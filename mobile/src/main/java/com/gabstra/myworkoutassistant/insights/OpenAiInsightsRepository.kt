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
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn

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
            streamText = { transportRequest, onChunk ->
                generateResponseStream(
                    config = config,
                    transportRequest = transportRequest,
                    onChunk = onChunk,
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
        )
        val finalText = accumulated.toString().ifBlank { "No insights were generated." }
        Log.d(
            LiteRtLmInsightsRepository.LOG_TAG,
            "${transportRequest.responseLogLabel}_start\n$finalText\n${transportRequest.responseLogLabel}_end"
        )
        return finalText
    }

    private suspend fun generateResponseStream(
        config: RemoteOpenAiConfig,
        transportRequest: WorkoutInsightsTransportRequest,
        onChunk: suspend (String) -> Unit,
    ) {
        val client = OpenAIOkHttpClient.builder()
            .apiKey(config.apiKey.trim())
            .baseUrl(normalizeBaseUrl(config.baseUrl))
            .build()

        Log.d(
            LiteRtLmInsightsRepository.LOG_TAG,
            "${transportRequest.requestLogLabel}" +
                "_start mode=${if (transportRequest.imagePngBytes != null) "image_text" else "text_only"} endpoint=${config.baseUrl.trim()} prompt_chars=${transportRequest.prompt.length} image_bytes=${transportRequest.imagePngBytes?.size ?: 0}"
        )

        val params = buildChatCompletionParams(
            config = config,
            transportRequest = transportRequest,
        )

        client.chat().completions().createStreaming(params).use { streamResponse ->
            consumeChatCompletionStream(streamResponse, onChunk)
        }
    }

    private fun buildChatCompletionParams(
        config: RemoteOpenAiConfig,
        transportRequest: WorkoutInsightsTransportRequest,
    ): ChatCompletionCreateParams {
        val builder = ChatCompletionCreateParams.builder()
            .model(config.model.trim())
            .addSystemMessage(transportRequest.systemPrompt)

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
}
