package com.gabstra.myworkoutassistant.insights

import android.content.Context
import android.util.Log
import com.google.ai.edge.litertlm.Backend
import com.google.ai.edge.litertlm.ConversationConfig
import com.google.ai.edge.litertlm.Engine
import com.google.ai.edge.litertlm.EngineConfig
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
)

class LiteRtLmInsightsRepository(
    private val context: Context,
) {
    companion object {
        suspend fun prewarmIfConfigured(context: Context) {
            val modelPath = LiteRtLmModelStore.getConfiguredModelPath(context) ?: return
            runCatching {
                val engineHandle = LiteRtLmEnginePool.acquire(
                    modelPath = modelPath,
                    cacheDir = context.cacheDir.absolutePath,
                    nativeLibraryDir = context.applicationInfo.nativeLibraryDir
                )
                LiteRtLmEnginePool.release(engineHandle)
            }.onFailure { throwable ->
                Log.w("WorkoutInsights", "litert_prewarm_failed", throwable)
            }
        }
    }

    fun generateInsights(
        title: String,
        prompt: String,
    ): Flow<WorkoutInsightsChunk> = flow {
        val modelPath = LiteRtLmModelStore.getConfiguredModelPath(context)
            ?: error("No LiteRT-LM model configured.")

        val accumulated = StringBuilder()
        val engineHandle = LiteRtLmEnginePool.acquire(
            modelPath = modelPath,
            cacheDir = context.cacheDir.absolutePath,
            nativeLibraryDir = context.applicationInfo.nativeLibraryDir
        )

        try {
            val conversationConfig = ConversationConfig(
                systemInstruction = com.google.ai.edge.litertlm.Contents.of(
                    WORKOUT_INSIGHTS_SYSTEM_PROMPT.trimIndent()
                ),
                samplerConfig = SamplerConfig(
                    temperature = 0.3,
                    topK = 20,
                    topP = 0.9
                )
            )
            engineHandle.engine.createConversation(conversationConfig).use { conversation ->
                conversation.sendMessageAsync(prompt).collect { message ->
                    val chunk = message.toString()
                    if (chunk.isNotBlank()) {
                        accumulated.append(chunk)
                        emit(WorkoutInsightsChunk(title = title, text = accumulated.toString()))
                    }
                }
            }
        } finally {
            LiteRtLmEnginePool.release(engineHandle)
        }
    }.flowOn(Dispatchers.IO)
}

private data class EngineHandle(
    val engine: Engine,
    val modelPath: String,
    val backendName: String,
)

private object LiteRtLmEnginePool {
    private val mutex = Mutex()
    private var cachedHandle: EngineHandle? = null
    private var refCount: Int = 0

    suspend fun acquire(
        modelPath: String,
        cacheDir: String,
        nativeLibraryDir: String,
    ): EngineHandle = mutex.withLock {
        val cached = cachedHandle
        if (cached != null && cached.modelPath == modelPath) {
            refCount += 1
            return cached
        }

        cachedHandle?.engine?.close()
        val created = createEngineWithFallback(modelPath, cacheDir, nativeLibraryDir)
        cachedHandle = created
        refCount = 1
        created
    }

    suspend fun release(handle: EngineHandle) {
        mutex.withLock {
            if (cachedHandle !== handle) return@withLock
            refCount = (refCount - 1).coerceAtLeast(0)
        }
    }

    private fun createEngineWithFallback(
        modelPath: String,
        cacheDir: String,
        nativeLibraryDir: String,
    ): EngineHandle {
        val backendFactories = listOf(
            "GPU" to { Backend.GPU() },
            "NPU" to { Backend.NPU(nativeLibraryDir = nativeLibraryDir) },
            "CPU" to { Backend.CPU() }
        )
        var lastError: Throwable? = null
        for ((name, factory) in backendFactories) {
            try {
                val engine = Engine(
                    EngineConfig(
                        modelPath = modelPath,
                        backend = factory(),
                        cacheDir = cacheDir
                    )
                )
                engine.initialize()
                return EngineHandle(engine = engine, modelPath = modelPath, backendName = name)
            } catch (throwable: Throwable) {
                lastError = throwable
            }
        }
        throw IllegalStateException(
            "Unable to initialize LiteRT-LM on GPU, NPU, or CPU.",
            lastError
        )
    }
}
