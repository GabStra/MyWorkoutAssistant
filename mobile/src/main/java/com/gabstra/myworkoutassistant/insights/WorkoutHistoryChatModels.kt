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
    val isUiOnly: Boolean = false,
)

internal fun selectConversationWindowMessages(
    messages: List<HistoryChatMessage>,
    maxTurns: Int,
    maxChars: Int,
    includeAssistantMessages: Boolean = true,
    tokenCounter: ((String) -> Int?)? = null,
    maxTokens: Int? = null,
): List<HistoryChatMessage> {
    val conversationMessages = messages.filterNot { it.isUiOnly }
    if (conversationMessages.isEmpty()) return emptyList()

    val turnGroups = mutableListOf<List<HistoryChatMessage>>()
    val currentTurn = mutableListOf<HistoryChatMessage>()

    fun flushCurrentTurn() {
        if (currentTurn.isEmpty()) return
        turnGroups += currentTurn.toList()
        currentTurn.clear()
    }

    for (message in conversationMessages) {
        when (message.role) {
            HistoryChatMessageRole.User -> {
                flushCurrentTurn()
                currentTurn += message
            }
            HistoryChatMessageRole.Assistant -> {
                if (!includeAssistantMessages) {
                    flushCurrentTurn()
                    continue
                }
                currentTurn += message
            }
        }
    }
    flushCurrentTurn()

    val selectedTurns = turnGroups.takeLast(maxTurns).toMutableList()
    while (
        selectedTurns.size > 1 &&
        selectedTurns.sumOf { turn -> turn.sumOf { it.content.trim().length } } > maxChars
    ) {
        selectedTurns.removeAt(0)
    }
    if (tokenCounter != null && maxTokens != null) {
        while (selectedTurns.size > 1) {
            val totalTokens = selectedTurns.sumOf { turn ->
                turn.sumOf { tokenCounter(it.content)?.toLong() ?: 0L }
            }
            if (totalTokens <= maxTokens) break
            selectedTurns.removeAt(0)
        }
    }
    return selectedTurns.flatten()
}

internal object HistoryChatLimits {
    /** Max prior user+assistant pairs kept in the composed prompt (excluding the new user turn). */
    const val MAX_PRIOR_TURNS = 8

    /** Soft cap on characters for the "Conversation so far" block inside the user prompt. */
    const val MAX_CONVERSATION_HISTORY_CHARS = 12_000

    /**
     * Hard cap (exact Gemma token count) on the conversation window shared with the
     * system prompt, tool definitions and tool outputs inside the model context.
     */
    const val MAX_CONVERSATION_HISTORY_TOKENS = 3_000

    /**
     * Upper bound on **new** tokens generated per assistant reply (local LiteRT decode and remote
     * `max_completion_tokens`). Allows complete explanations and practical follow-up guidance.
     */
    const val MAX_OUTPUT_TOKENS = 1536
}
