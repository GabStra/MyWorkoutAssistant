package com.gabstra.myworkoutassistant.insights

import android.content.Context
import android.util.Log
import com.google.ai.edge.litertlm.Backend
import com.google.ai.edge.litertlm.Content
import com.google.ai.edge.litertlm.Contents
import com.google.ai.edge.litertlm.ConversationConfig
import com.google.ai.edge.litertlm.Engine
import com.google.ai.edge.litertlm.EngineConfig
import com.google.ai.edge.litertlm.LogSeverity
import com.google.ai.edge.litertlm.Message
import com.google.ai.edge.litertlm.SamplerConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

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
)

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

private data class EngineHandle(
    val engine: Engine,
    val modelPath: String,
    val backendName: String,
    val visionEnabled: Boolean,
    val backendPreference: LiteRtLmBackendPreference,
)

private object LiteRtLmEnginePool {
    private val mutex = Mutex()
    private var cachedHandle: EngineHandle? = null
    private var refCount: Int = 0

    suspend fun acquire(
        modelPath: String,
        cacheDir: String,
        nativeLibraryDir: String,
        visionEnabled: Boolean,
    ): EngineHandle = mutex.withLock {
        val cached = cachedHandle
        if (
            cached != null &&
            cached.modelPath == modelPath &&
            cached.visionEnabled == visionEnabled &&
            cached.backendPreference == LiteRtLmModelStore.getBackendPreference(appContext)
        ) {
            refCount += 1
            return cached
        }
        Engine.setNativeMinLogSeverity(LogSeverity.ERROR)

        cachedHandle?.engine?.close()
        val created = createEngine(
            modelPath = modelPath,
            cacheDir = cacheDir,
            nativeLibraryDir = nativeLibraryDir,
            visionEnabled = visionEnabled,
            backendPreference = LiteRtLmModelStore.getBackendPreference(appContext)
        )
        cachedHandle = created
        refCount = 1
        created
    }

    lateinit var appContext: Context

    suspend fun release(handle: EngineHandle) {
        mutex.withLock {
            if (cachedHandle !== handle) return@withLock
            refCount = (refCount - 1).coerceAtLeast(0)
        }
    }

    suspend fun closeIfIdle() {
        mutex.withLock {
            if (refCount > 0) return@withLock
            cachedHandle?.engine?.close()
            cachedHandle = null
        }
    }

    private fun createEngine(
        modelPath: String,
        cacheDir: String,
        nativeLibraryDir: String,
        visionEnabled: Boolean,
        backendPreference: LiteRtLmBackendPreference,
    ): EngineHandle {
        val backend = when (backendPreference) {
            LiteRtLmBackendPreference.GPU -> Backend.GPU()
            LiteRtLmBackendPreference.CPU -> Backend.CPU()
        }
        val engine = Engine(
            EngineConfig(
                modelPath = modelPath,
                backend = backend,
                visionBackend = if (visionEnabled) backend else null,
                cacheDir = cacheDir
            )
        )
        engine.initialize()
        return EngineHandle(
            engine = engine,
            modelPath = modelPath,
            backendName = backendPreference.label,
            visionEnabled = visionEnabled,
            backendPreference = backendPreference
        )
    }
}

private suspend fun releaseChartAnalysisResources() {
    LiteRtLmEnginePool.closeIfIdle()
    Runtime.getRuntime().gc()
    System.runFinalization()
}

internal fun buildHeartRateChartAwarePrompt(prompt: String): String = buildString {
    append(stripRedundantHeartRateTextMetrics(prompt).trimEnd())
    append("\n\nAttached image context:\n")
    append("- The attached image is the workout session heart-rate chart.\n")
    append("- Use it to understand shape, peaks, drift, and recovery timing.\n")
    append("- Prefer explicit text metrics over conflicting image cues.\n")
}

internal fun stripRedundantHeartRateTextMetrics(
    prompt: String,
): String = prompt
    .lineSequence()
    .filterNot { line ->
        line.trimStart().startsWith("HR ")
    }
    .joinToString("\n")

private suspend fun LiteRtLmInsightsRepository.generateResponse(
    modelPath: String,
    transportRequest: WorkoutInsightsTransportRequest,
): String {
    val accumulated = StringBuilder()
    generateResponseStream(
        modelPath = modelPath,
        transportRequest = transportRequest,
        onChunk = { chunk -> accumulated.append(chunk) }
        ,
        onProgress = { _, _ -> }
    )
    val finalText = accumulated.toString().ifBlank { "No insights were generated." }
    logWorkoutInsightsBlock(
        LiteRtLmInsightsRepository.LOG_TAG,
        transportRequest.responseLogLabel,
        finalText
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

    LiteRtLmEnginePool.appContext = context.applicationContext
    val engineHandle = LiteRtLmEnginePool.acquire(
        modelPath = modelPath,
        cacheDir = context.cacheDir.absolutePath,
        nativeLibraryDir = context.applicationInfo.nativeLibraryDir,
        visionEnabled = transportRequest.imagePngBytes != null
    )

    try {
        Log.d(
            LiteRtLmInsightsRepository.LOG_TAG,
            "${transportRequest.requestLogLabel}" +
                "_start mode=${if (transportRequest.imagePngBytes != null) "image_text" else "text_only"} backend=${engineHandle.backendName} prompt_chars=${transportRequest.prompt.length} image_bytes=${transportRequest.imagePngBytes?.size ?: 0}"
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
        val conversationConfig = ConversationConfig(
            systemInstruction = Contents.of(transportRequest.systemPrompt),
            samplerConfig = SamplerConfig(
                temperature = 1.0,
                topK = 64,
                topP = 0.95
            )
        )
        engineHandle.engine.createConversation(conversationConfig).use { conversation ->
            val responseFlow = if (transportRequest.imagePngBytes != null) {
                conversation.sendMessageAsync(
                    Contents.of(
                        Content.ImageBytes(transportRequest.imagePngBytes),
                        Content.Text(transportRequest.prompt)
                    )
                )
            } else {
                conversation.sendMessageAsync(transportRequest.prompt)
            }
            responseFlow.collect { message ->
                val chunk = message.toString()
                if (chunk.isNotBlank()) {
                    onChunk(chunk)
                }
            }
        }
    } finally {
        LiteRtLmEnginePool.release(engineHandle)
    }
}

private suspend fun LiteRtLmInsightsRepository.generateChartAnalysisWithTimelineToolsResponse(
    modelPath: String,
    transportRequest: WorkoutInsightsTransportRequest,
    onProgress: suspend (WorkoutInsightsPhase, String) -> Unit,
): String {
    LiteRtLmEnginePool.appContext = context.applicationContext
    val engineHandle = LiteRtLmEnginePool.acquire(
        modelPath = modelPath,
        cacheDir = context.cacheDir.absolutePath,
        nativeLibraryDir = context.applicationInfo.nativeLibraryDir,
        visionEnabled = true
    )
    val timeline = requireNotNull(transportRequest.chartTimelineToolContext)
    val toolExecutor = WorkoutInsightsChartTimelineToolExecutor(timeline)

    try {
        val conversationConfig = ConversationConfig(
            systemInstruction = Contents.of(transportRequest.systemPrompt),
            samplerConfig = SamplerConfig(
                temperature = 1.0,
                topK = 64,
                topP = 0.95
            ),
            tools = toolExecutor.liteRtTools(),
            automaticToolCalling = false
        )
        engineHandle.engine.createConversation(conversationConfig).use { conversation ->
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
            var responseMessage = conversation.sendMessage(
                Contents.of(
                    Content.ImageBytes(requireNotNull(transportRequest.imagePngBytes)),
                    Content.Text(transportRequest.prompt)
                )
            )
            logLiteRtAssistantMessage(
                requestLogLabel = transportRequest.requestLogLabel,
                turnNumber = 1,
                message = responseMessage
            )
            repeat(MAX_INSIGHTS_TOOL_ROUNDS) { round ->
                val toolCalls = responseMessage.toolCalls
                if (toolCalls.isEmpty()) {
                    Log.d(
                        LiteRtLmInsightsRepository.LOG_TAG,
                        "${transportRequest.requestLogLabel}_tool_loop_exit reason=no_tool_calls turn=${round + 1}"
                    )
                    return extractLiteRtText(responseMessage)
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
                    logWorkoutInsightsBlock(
                        LiteRtLmInsightsRepository.LOG_TAG,
                        "${transportRequest.requestLogLabel}_tool_round_${round + 1}_${toolCall.name}_arguments",
                        renderForInsightLog(toolCall.arguments)
                    )
                    val payload = toolExecutor.executeToJsonString(
                        name = toolCall.name,
                        arguments = toolCall.arguments
                    )
                    logWorkoutInsightsBlock(
                        LiteRtLmInsightsRepository.LOG_TAG,
                        "${transportRequest.requestLogLabel}_tool_round_${round + 1}_${toolCall.name}_result",
                        payload
                    )
                    Content.ToolResponse(toolCall.name, payload)
                }
                logWorkoutInsightsBlock(
                    LiteRtLmInsightsRepository.LOG_TAG,
                    "${transportRequest.requestLogLabel}_turn_${round + 2}_tool_message",
                    toolResponses.joinToString("\n\n") { toolResponse ->
                        "Tool: ${toolResponse.name}\nPayload:\n${toolResponse.response}"
                    }
                )

                responseMessage = conversation.sendMessage(
                    Message.Companion.tool(Contents.of(toolResponses))
                )
                logLiteRtAssistantMessage(
                    requestLogLabel = transportRequest.requestLogLabel,
                    turnNumber = round + 2,
                    message = responseMessage
                )
            }

            Log.d(
                LiteRtLmInsightsRepository.LOG_TAG,
                "${transportRequest.requestLogLabel}_tool_loop_exit reason=tool_budget_exhausted rounds=$MAX_INSIGHTS_TOOL_ROUNDS"
            )
            return extractLiteRtText(responseMessage)
        }
    } finally {
        LiteRtLmEnginePool.release(engineHandle)
    }
}

private suspend fun LiteRtLmInsightsRepository.generateToolCallingResponse(
    modelPath: String,
    transportRequest: WorkoutInsightsTransportRequest,
    onProgress: suspend (WorkoutInsightsPhase, String) -> Unit,
): String {
    LiteRtLmEnginePool.appContext = context.applicationContext
    val engineHandle = LiteRtLmEnginePool.acquire(
        modelPath = modelPath,
        cacheDir = context.cacheDir.absolutePath,
        nativeLibraryDir = context.applicationInfo.nativeLibraryDir,
        visionEnabled = false
    )
    val toolContext = requireNotNull(transportRequest.toolContext)
    val toolExecutor = WorkoutInsightsToolExecutor(toolContext)

    try {
        val conversationConfig = ConversationConfig(
            systemInstruction = Contents.of(transportRequest.systemPrompt),
            samplerConfig = SamplerConfig(
                temperature = 1.0,
                topK = 64,
                topP = 0.95
            ),
            tools = toolExecutor.liteRtTools(),
            automaticToolCalling = false
        )
        engineHandle.engine.createConversation(conversationConfig).use { conversation ->
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
            var responseMessage = conversation.sendMessage(transportRequest.prompt)
            logLiteRtAssistantMessage(
                requestLogLabel = transportRequest.requestLogLabel,
                turnNumber = 1,
                message = responseMessage
            )
            repeat(MAX_INSIGHTS_TOOL_ROUNDS) { round ->
                val toolCalls = responseMessage.toolCalls
                if (toolCalls.isEmpty()) {
                    Log.d(
                        LiteRtLmInsightsRepository.LOG_TAG,
                        "${transportRequest.requestLogLabel}_tool_loop_exit reason=no_tool_calls turn=${round + 1}"
                    )
                    return extractLiteRtText(responseMessage)
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
                    logWorkoutInsightsBlock(
                        LiteRtLmInsightsRepository.LOG_TAG,
                        "${transportRequest.requestLogLabel}_tool_round_${round + 1}_${toolCall.name}_arguments",
                        renderForInsightLog(toolCall.arguments)
                    )
                    val payload = toolExecutor.executeToJsonString(
                        name = toolCall.name,
                        arguments = toolCall.arguments
                    )
                    logWorkoutInsightsBlock(
                        LiteRtLmInsightsRepository.LOG_TAG,
                        "${transportRequest.requestLogLabel}_tool_round_${round + 1}_${toolCall.name}_result",
                        payload
                    )
                    Content.ToolResponse(toolCall.name, payload)
                }
                logWorkoutInsightsBlock(
                    LiteRtLmInsightsRepository.LOG_TAG,
                    "${transportRequest.requestLogLabel}_turn_${round + 2}_tool_message",
                    toolResponses.joinToString("\n\n") { toolResponse ->
                        "Tool: ${toolResponse.name}\nPayload:\n${toolResponse.response}"
                    }
                )

                responseMessage = conversation.sendMessage(
                    Message.Companion.tool(Contents.of(toolResponses))
                )
                logLiteRtAssistantMessage(
                    requestLogLabel = transportRequest.requestLogLabel,
                    turnNumber = round + 2,
                    message = responseMessage
                )
            }

            Log.d(
                LiteRtLmInsightsRepository.LOG_TAG,
                "${transportRequest.requestLogLabel}_tool_loop_exit reason=tool_budget_exhausted rounds=$MAX_INSIGHTS_TOOL_ROUNDS"
            )
            return extractLiteRtText(responseMessage)
        }
    } finally {
        LiteRtLmEnginePool.release(engineHandle)
    }
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

private fun extractLiteRtText(
    message: Message,
): String {
    return message.contents.contents
        .mapNotNull { content ->
            when (content) {
                is Content.Text -> content.text
                else -> null
            }
        }
        .joinToString("")
        .ifBlank { message.toString() }
}

private fun logLiteRtAssistantMessage(
    requestLogLabel: String,
    turnNumber: Int,
    message: Message,
) {
    val text = extractLiteRtText(message)
    val toolCalls = message.toolCalls
    val rendered = buildString {
        append("Text:\n")
        append(text.ifBlank { "<empty>" })
        if (toolCalls.isNotEmpty()) {
            append("\n\nTool calls:\n")
            append(
                toolCalls.joinToString("\n\n") { toolCall ->
                    buildString {
                        append("Tool: ")
                        append(toolCall.name)
                        append("\nArguments:\n")
                        append(renderForInsightLog(toolCall.arguments))
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

internal fun buildHeartRateChartImageOnlyPrompt(
    chartAnalysisContext: String? = null,
    chartTimelineToolContext: WorkoutInsightsChartTimelineContext? = null,
): String = buildString {
    appendLine("Analyze the attached workout session heart-rate chart only.")
    appendLine("Use only what is visible in the chart and any timeline context explicitly provided below.")
    appendLine("Do not infer workout quality, fatigue, exercise type, or performance from the chart alone.")
    appendLine("Do not estimate exact bpm values, intensity zones, or exact recovery durations from the image.")
    appendLine("If the image is unclear or the pattern is ambiguous, say so plainly.")

    when {
        chartTimelineToolContext != null -> {
            appendLine()
            appendLine("Session duration: ${chartTimelineToolContext.durationSeconds} seconds from start to end.")
            appendLine(
                "Tool available: get_session_timeline_for_time_range(start_seconds, end_seconds), " +
                        "using inclusive elapsed seconds from workout start."
            )
            appendLine(
                "Use the tool only when visible features would be materially clearer with block names or timing, " +
                        "especially repeated peaks, phase changes, long recoveries, or late-session changes."
            )
            appendLine(
                "If the chart appears to contain repeated peaks or distinct phases, prefer at least one targeted tool call before finalizing."
            )
            appendLine("If tool output conflicts with the chart, trust the chart.")
        }

        else -> {
            chartAnalysisContext
                ?.trim()
                ?.takeIf { it.isNotBlank() }
                ?.let { context ->
                    appendLine()
                    appendLine("Provided timeline context (elapsed time from workout start; contiguous blocks):")
                    appendLine(context)
                    appendLine("Use it only to align visible features with likely work, rest, or transition periods.")
                    appendLine("If the pasted timeline conflicts with the chart, trust the chart.")
                }
        }
    }

    appendLine()
    appendLine("Focus only on chart-supported observations such as:")
    appendLine("- overall pattern: steady, intermittent, phased, or unclear")
    appendLine("- repeatability of visible peaks: similar, fading, building, or unclear")
    appendLine("- recovery shape between peaks: clear drop, partial drop, or unclear")
    appendLine("- late-session behavior: upward drift, stable pattern, reduced peaks, or unclear")
    appendLine("- obvious transitions: warm-up-like rise, repeated work/rest cycles, cooldown-like fall, or unclear")

    appendLine()
    appendLine("Output requirements:")
    appendLine("- keep the analysis concise and practical")
    appendLine("- report only observations that are visually supported")
    appendLine("- prefer cautious wording when evidence is mixed")
    append("- do not restate timeline context unless it changes the interpretation")
}

internal fun buildPromptWithHeartRateChartAnalysis(
    prompt: String,
    chartAnalysis: String?,
    supportingMarkdown: String? = null,
): String = buildString {
    append(prompt.trimEnd())
    formatHeartRateChartAnalysisForPrompt(
        chartAnalysis = chartAnalysis,
        supportingMarkdown = supportingMarkdown
    )?.let {
        append("\n\nHeart-rate chart observations:\n")
        append(it)
        append("\n\nTreat chart observations as secondary context for the final insight.")
        append("\nPrefer explicit workout metrics over conflicting chart observation wording.")
        append("\nDo not let chart wording override plan, previous, or best-to-date comparisons.")
    }
}

internal fun formatHeartRateChartAnalysisForPrompt(
    chartAnalysis: String?,
    supportingMarkdown: String? = null,
): String? {
    val raw = chartAnalysis?.takeUnless { it.isBlank() || it == "No insights were generated." } ?: return null
    val sanitized = sanitizeInsightMarkdown(normalizeChartAnalysisTokens(raw))
    val structuredMetrics = parseStructuredHeartRateMetrics(supportingMarkdown)
    val structuredLines = mutableListOf<String>()
    var currentPrefix = "CHART NOTE"

    sanitized.lineSequence()
        .map(String::trim)
        .filter { it.isNotBlank() }
        .forEach { line ->
            when {
                line.equals("## Chart Summary", ignoreCase = true) -> currentPrefix = "CHART SUMMARY"
                line.equals("## Chart Signals", ignoreCase = true) -> currentPrefix = "CHART SIGNAL"
                line.startsWith("SUMMARY:", ignoreCase = true) ->
                    structuredLines += "CHART SUMMARY ${line.substringAfter(':').trim()}"
                line.startsWith("SIGNAL:", ignoreCase = true) ->
                    structuredLines += "CHART SIGNAL ${line.substringAfter(':').trim()}"
                line.startsWith("- ") ->
                    structuredLines += "$currentPrefix ${line.removePrefix("- ").trim()}"
                else -> structuredLines += "$currentPrefix $line"
            }
        }

    return structuredLines
        .map { it.replace(Regex("\\s+"), " ").trim() }
        .filter { it.length > "CHART NOTE ".length }
        .filterNot(::isUnreliableChartMetricLine)
        .filter { chartLine -> isChartLineConsistentWithMetrics(chartLine, structuredMetrics) }
        .distinct()
        .take(4)
        .takeIf { it.isNotEmpty() }
        ?.joinToString("\n")
}

private fun normalizeChartAnalysisTokens(
    chartAnalysis: String,
): String {
    return chartAnalysis.replace(
        Regex("""(?i)(?<=.)(?=(?:SUMMARY:|SIGNAL:|##\s*Chart\s+Summary|##\s*Chart\s+Signals))"""),
        "\n"
    )
}

private data class StructuredHeartRateMetrics(
    val avgPercentMaxHr: Int?,
    val peakPercentMaxHr: Int?,
    val highIntensityExposurePercent: Int?,
)

private fun parseStructuredHeartRateMetrics(
    markdown: String?,
): StructuredHeartRateMetrics {
    val source = markdown.orEmpty()
    return StructuredHeartRateMetrics(
        avgPercentMaxHr = Regex("""Avg % max HR:\s*(\d{1,3})%""", RegexOption.IGNORE_CASE)
            .find(source)
            ?.groupValues
            ?.getOrNull(1)
            ?.toIntOrNull(),
        peakPercentMaxHr = Regex("""Peak % max HR:\s*(\d{1,3})%""", RegexOption.IGNORE_CASE)
            .find(source)
            ?.groupValues
            ?.getOrNull(1)
            ?.toIntOrNull(),
        highIntensityExposurePercent =
            Regex("""High-intensity exposure:\s*(\d{1,3})%""", RegexOption.IGNORE_CASE)
                .find(source)
                ?.groupValues
                ?.getOrNull(1)
                ?.toIntOrNull(),
    )
}

private fun isUnreliableChartMetricLine(
    line: String,
): Boolean {
    val normalized = line.lowercase()
    return normalized.contains(" bpm") ||
        normalized.contains("between approximately") ||
        normalized.contains("between ") ||
        normalized.contains("high-intensity") ||
        normalized.contains("high heart rate") ||
        normalized.contains("shorter towards the end") ||
        normalized.contains("longer towards the end") ||
        normalized.contains("recoveries appear")
}

private fun isChartLineConsistentWithMetrics(
    line: String,
    metrics: StructuredHeartRateMetrics,
): Boolean {
    val normalized = line.lowercase()
    if (
        metrics.highIntensityExposurePercent == 0 &&
        metrics.peakPercentMaxHr != null &&
        metrics.peakPercentMaxHr <= 80 &&
        (normalized.contains("high-intensity") || normalized.contains("high heart rate"))
    ) {
        return false
    }
    return true
}
