package com.gabstra.myworkoutassistant.insights

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.os.Bundle
import android.os.IBinder
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.util.concurrent.ConcurrentHashMap

/** One tool call the model requested; [argumentsJson] is a JSON object. */
internal data class LlmSessionToolCall(
    val name: String,
    val argumentsJson: String,
)

internal sealed interface LlmSessionResponse {
    data class Text(val text: String) : LlmSessionResponse
    data class ToolCalls(val calls: List<LlmSessionToolCall>) : LlmSessionResponse
}

internal sealed interface LlmSessionMessage {
    data class User(val text: String) : LlmSessionMessage
    data class ImageText(val imagePath: String, val text: String) : LlmSessionMessage
    data class ToolResponses(val responses: List<Pair<String, String>>) : LlmSessionMessage
}

internal data class LlmSessionSpec(
    val modelPath: String,
    val cacheDir: String,
    val backendPreference: LiteRtLmBackendPreference,
    val visionEnabled: Boolean,
    val systemPrompt: String,
    val maxOutputToken: Int?,
    /** Ordered prior turns as (role, content); role is "user" or "model". */
    val initialMessages: List<Pair<String, String>>,
    /** Tool description JSON strings (OpenApiTool descriptions). */
    val toolSpecsJson: List<String>,
)

/**
 * A live conversation in the isolated :llm process. [sendMessage] streams
 * accumulated text through [onChunk] and returns the terminal response.
 */
internal interface LlmInferenceSession : AutoCloseable {
    suspend fun sendMessage(
        message: LlmSessionMessage,
        onChunk: suspend (String) -> Unit,
    ): LlmSessionResponse

    override fun close()
}

private sealed interface LlmStreamEvent {
    data class Chunk(val text: String) : LlmStreamEvent
    data class ToolCalls(val calls: List<LlmSessionToolCall>) : LlmStreamEvent
    data class Completed(val text: String) : LlmStreamEvent
}

/**
 * Main-process handle to the :llm engine. Owns the binding lifecycle and
 * converts an :llm process death into a readable failure on in-flight sends;
 * the next request transparently reconnects to a fresh process.
 */
internal class LlmEngineGatewayClient private constructor(private val appContext: Context) {
    private val mutex = Mutex()
    private var gateway: ILlmEngineGateway? = null
    private var connecting: CompletableDeferred<ILlmEngineGateway>? = null
    private val activeCallbacks = ConcurrentHashMap.newKeySet<ILlmStreamCallback>()

    suspend fun gateway(): ILlmEngineGateway {
        val deferred = mutex.withLock {
            gateway?.let { return it }
            connecting ?: CompletableDeferred<ILlmEngineGateway>().also { pending ->
                connecting = pending
                startConnectLocked(pending)
            }
        }
        return deferred.await()
    }

    private fun startConnectLocked(deferred: CompletableDeferred<ILlmEngineGateway>) {
        val connection = object : ServiceConnection {
            override fun onServiceConnected(name: ComponentName?, service: IBinder?) {
                val stub = service?.let { ILlmEngineGateway.Stub.asInterface(it) }
                if (stub == null) {
                    connecting = null
                    deferred.completeExceptionally(
                        IllegalStateException("The local AI engine service returned no gateway.")
                    )
                    return
                }
                runCatching {
                    stub.asBinder().linkToDeath(IBinder.DeathRecipient { handleBinderDeath() }, 0)
                }
                gateway = stub
                deferred.complete(stub)
            }

            override fun onServiceDisconnected(name: ComponentName?) {
                handleBinderDeath()
            }
        }
        val intent = Intent(appContext, LlmEngineService::class.java)
        if (!appContext.bindService(intent, connection, Context.BIND_AUTO_CREATE)) {
            connecting = null
            deferred.completeExceptionally(
                IllegalStateException("Could not start the isolated local AI engine service.")
            )
        }
    }

    private fun handleBinderDeath() {
        gateway = null
        connecting = null
        // Fail every in-flight send so its flow surfaces a readable error
        // instead of hanging; the next request reconnects to a fresh process.
        activeCallbacks.forEach { callback ->
            runCatching {
                callback.onError(
                    "The on-device AI engine crashed. It restarts automatically on the next request."
                )
            }
        }
        activeCallbacks.clear()
    }

    suspend fun createSession(context: Context, spec: LlmSessionSpec): LlmInferenceSession {
        val stub = gateway()
        val specBundle = Bundle().apply {
            putString(LlmEngineIpcContract.SPEC_MODEL_PATH, spec.modelPath)
            putString(LlmEngineIpcContract.SPEC_CACHE_DIR, spec.cacheDir)
            putString(LlmEngineIpcContract.SPEC_BACKEND_PREFERENCE, spec.backendPreference.name)
            putBoolean(LlmEngineIpcContract.SPEC_VISION_ENABLED, spec.visionEnabled)
            putString(LlmEngineIpcContract.SPEC_SYSTEM_PROMPT, spec.systemPrompt)
            spec.maxOutputToken?.let { putInt(LlmEngineIpcContract.SPEC_MAX_OUTPUT_TOKEN, it) }
            putParcelableArrayList(
                LlmEngineIpcContract.SPEC_INITIAL_MESSAGES,
                ArrayList(spec.initialMessages.map { (role, content) ->
                    Bundle().apply {
                        putString(LlmEngineIpcContract.MESSAGE_ROLE, role)
                        putString(LlmEngineIpcContract.MESSAGE_CONTENT, content)
                    }
                }),
            )
            putStringArrayList(
                LlmEngineIpcContract.SPEC_TOOL_SPECS,
                ArrayList(spec.toolSpecsJson),
            )
        }
        val sessionId = stub.createSession(specBundle)
        return IpcLlmSession(stub, sessionId, activeCallbacks) {
            runCatching { stub.closeSession(sessionId) }
        }
    }

    fun trimIfIdle() {
        val stub = gateway ?: return
        runCatching { stub.trimIfIdle() }
    }

    private class IpcLlmSession(
        private val stub: ILlmEngineGateway,
        private val sessionId: String,
        private val activeCallbacks: MutableSet<ILlmStreamCallback>,
        private val onClose: () -> Unit,
    ) : LlmInferenceSession {
        @Volatile
        private var closed = false

        override fun close() {
            if (closed) return
            closed = true
            onClose()
        }

        override suspend fun sendMessage(
            message: LlmSessionMessage,
            onChunk: suspend (String) -> Unit,
        ): LlmSessionResponse {
            val messageBundle = Bundle().apply {
                when (message) {
                    is LlmSessionMessage.User -> {
                        putString(LlmEngineIpcContract.MESSAGE_TYPE, "user")
                        putString(LlmEngineIpcContract.MESSAGE_TEXT, message.text)
                    }
                    is LlmSessionMessage.ImageText -> {
                        putString(LlmEngineIpcContract.MESSAGE_TYPE, "image_text")
                        putString(LlmEngineIpcContract.MESSAGE_IMAGE_PATH, message.imagePath)
                        putString(LlmEngineIpcContract.MESSAGE_TEXT, message.text)
                    }
                    is LlmSessionMessage.ToolResponses -> {
                        putString(LlmEngineIpcContract.MESSAGE_TYPE, "tool_responses")
                        putParcelableArrayList(
                            LlmEngineIpcContract.MESSAGE_TOOL_RESPONSES,
                            ArrayList(message.responses.map { (name, payload) ->
                                Bundle().apply {
                                    putString(LlmEngineIpcContract.TOOL_RESPONSE_NAME, name)
                                    putString(LlmEngineIpcContract.TOOL_RESPONSE_PAYLOAD, payload)
                                }
                            }),
                        )
                    }
                }
            }

            var terminal: LlmSessionResponse? = null
            while (terminal == null) {
                val event = streamEvents(messageBundle).first()
                when (event) {
                    is LlmStreamEvent.Chunk -> onChunk(event.text)
                    is LlmStreamEvent.ToolCalls -> terminal = LlmSessionResponse.ToolCalls(event.calls)
                    is LlmStreamEvent.Completed -> terminal = LlmSessionResponse.Text(event.text)
                }
            }
            return terminal
        }

        private fun streamEvents(messageBundle: Bundle): Flow<LlmStreamEvent> = callbackFlow {
            val callback = object : ILlmStreamCallback.Stub() {
                override fun onChunk(text: String?) {
                    if (!text.isNullOrEmpty()) trySend(LlmStreamEvent.Chunk(text))
                }

                override fun onToolCalls(toolCallsJson: String?) {
                    trySend(LlmStreamEvent.ToolCalls(parseToolCalls(requireNotNull(toolCallsJson))))
                    close()
                }

                override fun onCompleted(text: String?) {
                    trySend(LlmStreamEvent.Completed(text.orEmpty()))
                    close()
                }

                override fun onError(message: String?) {
                    close(IllegalStateException(message ?: "The local AI engine failed."))
                }
            }
            activeCallbacks.add(callback)
            try {
                stub.sendMessage(sessionId, messageBundle, callback)
            } catch (t: Throwable) {
                close(IllegalStateException("The on-device AI engine failed during generation.", t))
            }
            awaitClose { activeCallbacks.remove(callback) }
        }

        private fun parseToolCalls(toolCallsJson: String): List<LlmSessionToolCall> {
            val array = org.json.JSONArray(toolCallsJson)
            val calls = (0 until array.length()).map { index ->
                val entry = array.getJSONObject(index)
                LlmSessionToolCall(
                    name = entry.getString("name"),
                    argumentsJson = entry.optJSONObject("arguments")?.toString()
                        ?: entry.optString("arguments"),
                )
            }
            return calls
        }
    }

    companion object {
        @Volatile
        private var instance: LlmEngineGatewayClient? = null

        fun obtain(context: Context): LlmEngineGatewayClient =
            instance ?: synchronized(this) {
                instance ?: LlmEngineGatewayClient(context.applicationContext).also { instance = it }
            }
    }
}
