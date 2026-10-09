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

    /**
     * KV cache, activations and backend copies allocate on top of the mapped
     * weights, so the guard demands headroom beyond the file size. The margin
     * is deliberately modest: since inference moved to the isolated :llm
     * process, an overshoot kills only that process and surfaces as a
     * readable, recoverable error — not an app crash.
     */
    private const val LOW_MEMORY_MARGIN_BYTES = 512L * 1024 * 1024

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
        val modelFile = File(modelPath)
        val modelBytes = modelFile.length()
        if (modelBytes <= 0L) return
        val activityManager =
            context.getSystemService(Context.ACTIVITY_SERVICE) as? ActivityManager ?: return
        val memoryInfo = ActivityManager.MemoryInfo().also { activityManager.getMemoryInfo(it) }
        val requiredBytes = modelBytes + LOW_MEMORY_MARGIN_BYTES
        if (memoryInfo.availMem < requiredBytes) {
            throw UnsafeModelException(
                "Not enough free memory to load this model (${modelBytes / 1_000_000} MB file, " +
                    "${memoryInfo.availMem / 1_000_000} MB free). ${adviceFor(modelFile.name)}",
            )
        }
    }

    /**
     * Suggesting a smaller model is only useful when a smaller one exists;
     * for the compact tier the realistic fix is freeing memory (a reboot is
     * the fastest reliable way on Samsung devices).
     */
    private fun adviceFor(modelFileName: String): String {
        val name = modelFileName.lowercase()
        return when {
            "e2b" in name ->
                "This is already the smallest model — restart the phone to free memory, then try again."
            "e4b" in name ->
                "Close other apps, or use a smaller model (for example Gemma 4 E2B)."
            else ->
                "Close other apps, restart the phone, or use a smaller model."
        }
    }
}
