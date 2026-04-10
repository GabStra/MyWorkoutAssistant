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
)

enum class WorkoutInsightsPhase {
    CHART_ANALYSIS,
    FINAL_SYNTHESIS,
}

data class WorkoutInsightsRequest(
    val title: String,
    val prompt: String,
    val systemPrompt: String = WORKOUT_INSIGHTS_SYSTEM_PROMPT,
    val imagePngBytes: ByteArray? = null,
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
            streamText = { transportRequest, onChunk ->
                generateResponseStream(
                    modelPath = modelPath,
                    transportRequest = transportRequest,
                    onChunk = onChunk,
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
    append("- If the image conflicts with explicit text metrics, prefer the explicit text metrics.\n")
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
    )
    val finalText = accumulated.toString().ifBlank { "No insights were generated." }
    Log.d(
        LiteRtLmInsightsRepository.LOG_TAG,
        "${transportRequest.responseLogLabel}_start\n$finalText\n${transportRequest.responseLogLabel}_end"
    )
    return finalText
}

private suspend fun LiteRtLmInsightsRepository.generateResponseStream(
    modelPath: String,
    transportRequest: WorkoutInsightsTransportRequest,
    onChunk: suspend (String) -> Unit,
) {
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

internal fun buildHeartRateChartImageOnlyPrompt(): String = """
Analyze the attached workout session heart-rate chart only.
Do not use any hidden assumptions about the workout.
Describe only what the chart itself makes clear about:
- the approximate operating range
- whether the pattern looks steady, intermittent, or drifted
- whether repeated peaks look similar or fade
- whether recoveries look longer or shorter later in the session
If something is not clearly visible, omit it.
Keep the analysis concise and practical.
""".trimIndent()

internal fun buildPromptWithHeartRateChartAnalysis(
    prompt: String,
    chartAnalysis: String?,
): String = buildString {
    append(prompt.trimEnd())
    formatHeartRateChartAnalysisForPrompt(chartAnalysis)?.let {
        append("\n\nHeart-rate chart observations:\n")
        append(it)
        append("\n\nTreat chart observations as secondary context for the final insight.")
        append("\nPrefer explicit workout metrics when they disagree.")
        append("\nDo not let chart wording override plan, previous, or best-to-date comparisons.")
    }
}

internal fun formatHeartRateChartAnalysisForPrompt(
    chartAnalysis: String?,
): String? {
    val raw = chartAnalysis?.takeUnless { it.isBlank() || it == "No insights were generated." } ?: return null
    val sanitized = sanitizeInsightMarkdown(normalizeChartAnalysisTokens(raw))
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
