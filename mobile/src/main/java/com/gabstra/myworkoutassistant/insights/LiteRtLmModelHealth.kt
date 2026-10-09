package com.gabstra.myworkoutassistant.insights

import android.app.ActivityManager
import android.content.Context
import com.google.ai.edge.litertlm.BackendType
import com.google.ai.edge.litertlm.ModelInfo
import com.google.ai.edge.litertlm.Modality
import java.io.File

/**
 * Pre-flight checks that keep a broken or oversized model from taking the app
 * down in native code: bundle parse failures, missing backend support and low
 * free memory are surfaced as catchable, user-readable errors BEFORE
 * [com.google.ai.edge.litertlm.Engine.initialize] touches the model weights.
 */
internal object LiteRtLmModelHealth {
    /** The model cannot be safely loaded on this device as configured. */
    class UnsafeModelException(message: String, cause: Throwable? = null) :
        IllegalStateException(message, cause)

    data class Report(
        val speculativeDecodingSupported: Boolean,
        val gpuSupported: Boolean,
        val maxContextTokens: Int?,
    )

    private const val LOW_MEMORY_MARGIN_BYTES = 1L * 1024 * 1024 * 1024

    /**
     * Parses the bundle header only (weights are not loaded). Throws
     * [UnsafeModelException] when the file is not a readable LiteRT-LM bundle —
     * feeding it to the engine risks an uncatchable native crash.
     */
    fun inspect(modelPath: String): Report {
        val info = try {
            ModelInfo.from(modelPath)
        } catch (t: Throwable) {
            throw UnsafeModelException(
                "The selected model file could not be read as a LiteRT-LM bundle. " +
                    "Re-download it, or pick a different .litertlm file.",
                t,
            )
        }
        return info.use {
            Report(
                speculativeDecodingSupported =
                    (it as? ModelInfo.Llm)?.hasSpeculativeDecodingSupport() ?: false,
                gpuSupported = BackendType.GPU in it.supportedBackends(Modality.TEXT),
                maxContextTokens = runCatching { it.maxContextTokens() }.getOrNull(),
            )
        }
    }

    /**
     * Loading maps the model file and allocates KV/compute buffers on top; when
     * free memory cannot cover that, the OS may kill the process mid-load.
     * Refusing early turns that into a readable message instead.
     */
    fun requireEnoughFreeMemory(context: Context, modelPath: String) {
        val modelBytes = File(modelPath).length()
        if (modelBytes <= 0L) return
        val activityManager =
            context.getSystemService(Context.ACTIVITY_SERVICE) as? ActivityManager ?: return
        val memoryInfo = ActivityManager.MemoryInfo().also { activityManager.getMemoryInfo(it) }
        val requiredBytes = modelBytes + LOW_MEMORY_MARGIN_BYTES
        if (memoryInfo.availMem < requiredBytes) {
            throw UnsafeModelException(
                "Not enough free memory to load this model (${modelBytes / 1_000_000} MB file, " +
                    "${memoryInfo.availMem / 1_000_000} MB free). Close other apps, or use a " +
                    "smaller model (for example Gemma 4 E2B).",
            )
        }
    }
}
