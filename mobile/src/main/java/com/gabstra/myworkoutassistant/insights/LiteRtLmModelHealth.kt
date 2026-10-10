package com.gabstra.myworkoutassistant.insights

import com.google.ai.edge.litertlm.BackendType
import com.google.ai.edge.litertlm.ModelInfo
import com.google.ai.edge.litertlm.Modality

/**
 * Pre-flight checks that keep a broken model from taking the app down in
 * native code: bundle parse failures and missing backend support are surfaced
 * as catchable, user-readable errors BEFORE
 * [com.google.ai.edge.litertlm.Engine.initialize] touches the model weights.
 */
internal object LiteRtLmModelHealth {
    /** The model cannot be safely loaded on this device as configured. */
    open class UnsafeModelException(message: String, cause: Throwable? = null) :
        IllegalStateException(message, cause)

    data class Report(
        val speculativeDecodingSupported: Boolean,
        val gpuSupported: Boolean,
        val maxContextTokens: Int?,
    )

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
}
