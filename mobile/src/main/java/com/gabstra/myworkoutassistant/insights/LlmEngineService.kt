package com.gabstra.myworkoutassistant.insights

import android.app.Service
import android.content.Intent
import android.os.Bundle
import android.os.IBinder
import android.util.Log
import com.google.ai.edge.litertlm.Backend
import com.google.ai.edge.litertlm.Content
import com.google.ai.edge.litertlm.Contents
import com.google.ai.edge.litertlm.Conversation
import com.google.ai.edge.litertlm.ConversationConfig
import com.google.ai.edge.litertlm.Engine
import com.google.ai.edge.litertlm.EngineConfig
import com.google.ai.edge.litertlm.ExperimentalApi
import com.google.ai.edge.litertlm.ExperimentalFlags
import com.google.ai.edge.litertlm.LogSeverity
import com.google.ai.edge.litertlm.Message
import com.google.ai.edge.litertlm.SamplerConfig
import com.google.ai.edge.litertlm.ToolProvider
import com.google.ai.edge.litertlm.tool
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.concurrent.ConcurrentHashMap
import kotlin.time.Duration.Companion.minutes

/**
 * Runs the LiteRT-LM engine inside the isolated `:llm` process so a native
 * abort during inference can never take the main app down. Owns the engine
 * pool and one conversation per session; the main process drives tool rounds
 * by exchanging [LlmEngineIpcContract.MESSAGE_TOOL_RESPONSES] messages.
 */
class LlmEngineService : Service() {
    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val sessions = ConcurrentHashMap<String, LlmSessionState>()
    private var idleCloseJob: Job? = null

    private inner class LlmSessionState(
        val conversation: Conversation,
    ) {
        var sendJob: Job? = null
    }

    override fun onCreate() {
        super.onCreate()
        LiteRtLmEnginePool.appContext = applicationContext
    }

    override fun onBind(intent: Intent?): IBinder = gateway

    override fun onDestroy() {
        serviceScope.cancel()
        sessions.values.forEach { runCatching { it.conversation.close() } }
        sessions.clear()
        runCatching { kotlinx.coroutines.runBlocking { LiteRtLmEnginePool.closeIfIdleLocked() } }
        super.onDestroy()
    }

    /**
     * Closes the cached engine once no sessions remain for [IDLE_ENGINE_CLOSE_DELAY],
     * freeing the model weights while keeping the process warm; every engine use
     * reschedules this, and an in-flight session defers the close.
     */
    private fun scheduleIdleEngineClose() {
        idleCloseJob?.cancel()
        idleCloseJob = serviceScope.launch {
            while (true) {
                delay(IDLE_ENGINE_CLOSE_DELAY)
                if (sessions.isEmpty()) {
                    LiteRtLmEnginePool.closeIfIdleLocked()
                    return@launch
                }
            }
        }
    }

    private val gateway = object : ILlmEngineGateway.Stub() {
        override fun createSession(spec: Bundle): String {
            val sessionId = java.util.UUID.randomUUID().toString()
            // Engine initialization can take seconds; blocking a binder pool
            // thread is fine here — the :llm process has no UI to freeze.
            val conversation = kotlinx.coroutines.runBlocking {
                LiteRtLmEnginePool.acquireAndCreateConversation(
                modelPath = requireNotNull(spec.getString(LlmEngineIpcContract.SPEC_MODEL_PATH)),
                cacheDir = spec.getString(LlmEngineIpcContract.SPEC_CACHE_DIR)
                    ?: cacheDir.absolutePath,
                visionEnabled = spec.getBoolean(LlmEngineIpcContract.SPEC_VISION_ENABLED),
                backendPreference = LiteRtLmBackendPreference.fromStoredValue(
                    spec.getString(LlmEngineIpcContract.SPEC_BACKEND_PREFERENCE)
                ),
                systemPrompt = spec.getString(LlmEngineIpcContract.SPEC_SYSTEM_PROMPT).orEmpty(),
                maxOutputToken = spec.getInt(LlmEngineIpcContract.SPEC_MAX_OUTPUT_TOKEN)
                    .takeIf { spec.containsKey(LlmEngineIpcContract.SPEC_MAX_OUTPUT_TOKEN) },
                initialMessages = readInitialMessages(spec),
                toolSpecsJson = spec.getStringArrayList(LlmEngineIpcContract.SPEC_TOOL_SPECS)
                    .orEmpty(),
                )
            }
            sessions[sessionId] = LlmSessionState(conversation)
            scheduleIdleEngineClose()
            return sessionId
        }

        override fun sendMessage(sessionId: String?, message: Bundle?, callback: ILlmStreamCallback?) {
            if (sessionId == null || message == null || callback == null) return
            val session = sessions[sessionId] ?: run {
                callback.onError("The inference session has expired. Start the request again.")
                return
            }
            session.sendJob?.cancel()
            session.sendJob = serviceScope.launch {
                try {
                    runSend(session, message, callback)
                } catch (t: CancellationException) {
                    throw t
                } catch (t: Throwable) {
                    Log.w(LOG_TAG, "Send failed in :llm session", t)
                    callback.onError(t.message ?: t.javaClass.simpleName)
                } finally {
                    scheduleIdleEngineClose()
                }
            }
        }

        override fun cancelSession(sessionId: String?) {
            sessionId?.let { id -> sessions[id]?.sendJob?.cancel() }
        }

        override fun closeSession(sessionId: String?) {
            val id = sessionId ?: return
            sessions.remove(id)?.let { session ->
                session.sendJob?.cancel()
                runCatching { session.conversation.close() }
            }
        }

        override fun trimIfIdle() {
            serviceScope.launch { LiteRtLmEnginePool.closeIfIdleLocked() }
        }
    }

    private suspend fun runSend(
        session: LlmSessionState,
        message: Bundle,
        callback: ILlmStreamCallback,
    ) {
        val type = message.getString(LlmEngineIpcContract.MESSAGE_TYPE)
        val responseMessage = withContext(Dispatchers.Default) {
            when (type) {
                "image_text" -> collectStreaming(
                    session.conversation.sendMessageAsync(
                        Contents.of(
                            Content.ImageBytes(
                                File(requireNotNull(message.getString(LlmEngineIpcContract.MESSAGE_IMAGE_PATH)))
                                    .readBytes()
                            ),
                            Content.Text(message.getString(LlmEngineIpcContract.MESSAGE_TEXT).orEmpty()),
                        )
                    ),
                    callback,
                )
                "tool_responses" -> {
                    val responses = message.getParcelableArrayList<Bundle>(
                        LlmEngineIpcContract.MESSAGE_TOOL_RESPONSES
                    ).orEmpty().map { bundle ->
                        Content.ToolResponse(
                            requireNotNull(bundle.getString(LlmEngineIpcContract.TOOL_RESPONSE_NAME)),
                            requireNotNull(bundle.getString(LlmEngineIpcContract.TOOL_RESPONSE_PAYLOAD)),
                        )
                    }
                    session.conversation.sendMessage(
                        Message.Companion.tool(Contents.of(responses))
                    )
                }
                else -> collectStreaming(
                    session.conversation.sendMessageAsync(
                        message.getString(LlmEngineIpcContract.MESSAGE_TEXT).orEmpty()
                    ),
                    callback,
                )
            }
        }

        val toolCalls = responseMessage.toolCalls
        if (toolCalls.isEmpty()) {
            callback.onCompleted(extractLiteRtText(responseMessage))
        } else {
            callback.onToolCalls(
                JSONArray().apply {
                    toolCalls.forEach { toolCall ->
                        put(JSONObject(mapOf("name" to toolCall.name, "arguments" to toolCall.arguments)))
                    }
                }.toString()
            )
        }
    }

    private suspend fun collectStreaming(
        responseFlow: Flow<Message>,
        callback: ILlmStreamCallback,
    ): Message {
        var lastMessage: Message? = null
        responseFlow.collect { message ->
            lastMessage = message
            val chunk = extractLiteRtText(message)
            if (chunk.isNotEmpty()) {
                callback.onChunk(chunk)
            }
        }
        return lastMessage ?: error("The model returned no response.")
    }

    private fun readInitialMessages(spec: Bundle): List<Message> {
        val bundles = spec.getParcelableArrayList<Bundle>(
            LlmEngineIpcContract.SPEC_INITIAL_MESSAGES
        ).orEmpty()
        return bundles.map { bundle ->
            val content = requireNotNull(bundle.getString(LlmEngineIpcContract.MESSAGE_CONTENT))
            when (bundle.getString(LlmEngineIpcContract.MESSAGE_ROLE)) {
                "model" -> Message.Companion.model(content.trim())
                else -> Message.Companion.user(content.trim())
            }
        }
    }

    companion object {
        private const val LOG_TAG = "LlmEngineService"

        /** How long the loaded model stays resident after the last use. */
        private val IDLE_ENGINE_CLOSE_DELAY = 5.minutes
    }
}

/**
 * Engine pool for the :llm process. Kept here (not in the main process) so all
 * native inference — and every crash it could produce — stays contained.
 */
@OptIn(ExperimentalApi::class)
internal object LiteRtLmEnginePool {
    private val mutex = Mutex()
    private var cachedHandle: EngineHandle? = null

    lateinit var appContext: android.content.Context

    data class EngineHandle(
        val engine: Engine,
        val modelPath: String,
        val backendName: String,
        val visionEnabled: Boolean,
        val backendPreference: LiteRtLmBackendPreference,
    )

    suspend fun acquireAndCreateConversation(
        modelPath: String,
        cacheDir: String,
        visionEnabled: Boolean,
        backendPreference: LiteRtLmBackendPreference,
        systemPrompt: String,
        maxOutputToken: Int?,
        initialMessages: List<Message>,
        toolSpecsJson: List<String>,
    ): Conversation = mutex.withLock {
        val cached = cachedHandle
        val reusable = cached != null &&
            cached.modelPath == modelPath &&
            cached.visionEnabled == visionEnabled &&
            cached.backendPreference == backendPreference
        if (!reusable) {
            Engine.setNativeMinLogSeverity(LogSeverity.ERROR)
            // Refuse oversized loads before native code maps the file; a
            // mid-load low-memory kill cannot be caught or reported.
            LiteRtLmModelHealth.requireEnoughFreeMemory(appContext, modelPath)
            cachedHandle?.engine?.close()
            val created = createEngine(
                modelPath = modelPath,
                cacheDir = cacheDir,
                visionEnabled = visionEnabled,
                backendPreference = backendPreference,
            )
            cachedHandle = created
        }

        val handle = requireNotNull(cachedHandle)
        val conversationConfig = liteRtConversationConfig(
            systemPrompt = systemPrompt,
            initialMessages = initialMessages,
            tools = toolSpecsJson.map { spec -> tool(InsightsOpenApiTool(specFromJson(spec))) },
            automaticToolCalling = false,
            maxOutputToken = maxOutputToken,
        )
        handle.engine.createConversation(conversationConfig)
    }

    suspend fun closeIfIdleLocked() = mutex.withLock {
        if (cachedHandle != null) {
            cachedHandle?.engine?.close()
            cachedHandle = null
        }
    }

    private fun createEngine(
        modelPath: String,
        cacheDir: String,
        visionEnabled: Boolean,
        backendPreference: LiteRtLmBackendPreference,
    ): EngineHandle {
        val report = LiteRtLmModelHealth.inspect(modelPath)
        ExperimentalFlags.enableSpeculativeDecoding = report.speculativeDecodingSupported

        var resolvedPreference = backendPreference
        if (backendPreference == LiteRtLmBackendPreference.GPU && !report.gpuSupported) {
            Log.w(LOG_TAG, "Model bundle does not list GPU support; using the CPU backend instead.")
            resolvedPreference = LiteRtLmBackendPreference.CPU
        }

        val engine = try {
            initializeEngine(modelPath, resolvedPreference, visionEnabled, cacheDir)
        } catch (firstFailure: Throwable) {
            // GPU delegates can fail at initialization on some drivers; one CPU
            // retry is the catchable safety net (a native abort is not).
            if (resolvedPreference == LiteRtLmBackendPreference.CPU) throw firstFailure
            Log.w(LOG_TAG, "GPU engine initialization failed; retrying with the CPU backend.", firstFailure)
            resolvedPreference = LiteRtLmBackendPreference.CPU
            try {
                initializeEngine(modelPath, resolvedPreference, visionEnabled, cacheDir)
            } catch (cpuFailure: Throwable) {
                throw LiteRtLmModelHealth.UnsafeModelException(
                    "The local model failed to initialize on both the GPU and CPU backends: " +
                        (cpuFailure.message ?: cpuFailure.javaClass.simpleName),
                    cpuFailure,
                )
            }
        }
        return EngineHandle(
            engine = engine,
            modelPath = modelPath,
            backendName = resolvedPreference.label,
            visionEnabled = visionEnabled,
            backendPreference = backendPreference
        )
    }

    private fun initializeEngine(
        modelPath: String,
        backendPreference: LiteRtLmBackendPreference,
        visionEnabled: Boolean,
        cacheDir: String,
    ): Engine {
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
        return engine
    }

    private fun specFromJson(specJson: String): WorkoutInsightsToolSpec {
        val json = JSONObject(specJson)
        return WorkoutInsightsToolSpec(
            name = json.getString("name"),
            description = json.optString("description"),
            parametersSchema = json.optJSONObject("parametersSchema")?.toNullableMap() ?: emptyMap(),
            handler = { error("Tools execute in the main process, not in the :llm inference process.") },
        )
    }

    private fun JSONObject.toNullableMap(): Map<String, Any?> {
        val map = mutableMapOf<String, Any?>()
        for (key in keys()) {
            map[key] = get(key)
        }
        return map
    }

    private const val LOG_TAG = "LlmEngineService"
}

private fun liteRtConversationConfig(
    systemPrompt: String,
    initialMessages: List<Message> = emptyList(),
    tools: List<ToolProvider>?,
    automaticToolCalling: Boolean,
    maxOutputToken: Int? = null,
): ConversationConfig {
    val systemInstruction = Contents.of(systemPrompt)
    val samplerConfig = SamplerConfig(
        temperature = 1.0,
        topK = 64,
        topP = 0.95
    )
    return if (tools != null) {
        ConversationConfig(
            systemInstruction = systemInstruction,
            initialMessages = initialMessages,
            samplerConfig = samplerConfig,
            tools = tools,
            automaticToolCalling = automaticToolCalling,
            maxOutputToken = maxOutputToken,
        )
    } else {
        ConversationConfig(
            systemInstruction = systemInstruction,
            initialMessages = initialMessages,
            samplerConfig = samplerConfig,
            maxOutputToken = maxOutputToken,
        )
    }
}

private fun extractLiteRtText(message: Message): String {
    return message.contents.contents
        .mapNotNull { content ->
            when (content) {
                is Content.Text -> content.text
                else -> null
            }
        }
        .joinToString("")
}
