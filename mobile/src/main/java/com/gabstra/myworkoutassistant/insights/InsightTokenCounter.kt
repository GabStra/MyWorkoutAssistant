package com.gabstra.myworkoutassistant.insights

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.util.concurrent.atomic.AtomicReference

/**
 * Loads the bundled Gemma SentencePiece model once and exposes exact token
 * counts for prompt budgeting. Until the (one-off, background) load completes,
 * callers fall back to their char-based estimates.
 */
internal object InsightTokenCounter {
    private const val ASSET_PATH = "insights/gemma_tokenizer.model"

    @Volatile
    private var loadStarted = false

    private val tokenizer = AtomicReference<GemmaTokenizer?>(null)

    /** Starts the one-off background load if it has not started yet. Cheap after the first call. */
    fun ensure(context: Context) {
        if (tokenizer.get() != null || loadStarted) return
        synchronized(this) {
            if (loadStarted) return
            loadStarted = true
        }
        val appContext = context.applicationContext
        Thread {
            runCatching {
                appContext.assets.open(ASSET_PATH).use { GemmaTokenizer.from(it) }
            }.onSuccess(tokenizer::set)
        }.start()
    }

    /** Exact count, or null while the tokenizer is not loaded yet. */
    fun countTokens(text: String): Int? = tokenizer.get()?.countTokens(text)

    /** Synchronous load for first-use-critical paths (background dispatcher expected). */
    suspend fun loadNow(context: Context): GemmaTokenizer? {
        tokenizer.get()?.let { return it }
        val appContext = context.applicationContext
        return withContext(Dispatchers.IO) {
            val loaded = runCatching {
                appContext.assets.open(ASSET_PATH).use { GemmaTokenizer.from(it) }
            }.getOrNull()
            loaded?.let(tokenizer::set)
            loaded
        }
    }
}
