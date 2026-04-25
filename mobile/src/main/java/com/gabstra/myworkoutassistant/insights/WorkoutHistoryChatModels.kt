package com.gabstra.myworkoutassistant.insights

import java.util.UUID

/** Ephemeral in-memory chat thread (v1: not persisted). */
data class HistoryChatThread(
    val id: UUID = UUID.randomUUID(),
    val messages: List<HistoryChatMessage> = emptyList(),
)

enum class HistoryChatMessageRole {
    User,
    Assistant,
}

data class HistoryChatMessage(
    val id: UUID = UUID.randomUUID(),
    val role: HistoryChatMessageRole,
    val content: String,
    val createdAtEpochMs: Long = System.currentTimeMillis(),
)

internal object HistoryChatLimits {
    /** Max prior user+assistant pairs kept in the composed prompt (excluding the new user turn). */
    const val MAX_PRIOR_TURNS = 8

    /** Soft cap on characters for the "Conversation so far" block inside the user prompt. */
    const val MAX_CONVERSATION_HISTORY_CHARS = 12_000

    /**
     * Upper bound on **new** tokens generated per assistant reply (local LiteRT decode and remote
     * `max_completion_tokens`). Lower than a typical insight to keep chat replies shorter.
     */
    const val MAX_OUTPUT_TOKENS = 384
}
