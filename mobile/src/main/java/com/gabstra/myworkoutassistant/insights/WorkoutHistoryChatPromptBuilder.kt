package com.gabstra.myworkoutassistant.insights

private fun buildGenericHistoryChatBase(scope: String): String = """
You are the in-app history chat for $scope.

Use the **Exported history** block as the only source of workout facts. The user may ask anything about that history: summaries, comparisons, progress, targets, rest, timing, heart-rate context, labels, or practical next steps.

Answer the current user question directly. Use earlier conversation only as follow-up context. If the current question changes topic, follow the new topic.

Use whatever exported fields are relevant to the question. If a claim depends on numbers, the numbers must appear verbatim in the export. Do not invent, round, fix, or infer missing numbers.

Be concise by default. For simple questions, use one short paragraph or up to 3 bullets. Do not create a session-by-session breakdown, timeline, or headings unless the user asks for that.

If the export cannot support an answer, say what is missing. Do not give medical advice, diagnoses, or injury treatment.
""".trimIndent()

internal fun buildHistoryChatInlineSystemPrompt(
    basePrompt: String,
): String = basePrompt.trim()

internal fun buildExerciseHistoryChatSystemPrompt(): String =
    buildHistoryChatInlineSystemPrompt(buildGenericHistoryChatBase("one exercise"))

internal fun buildWorkoutSessionHistoryChatSystemPrompt(): String =
    buildHistoryChatInlineSystemPrompt(buildGenericHistoryChatBase("one completed workout session"))

private fun buildHistoryChatToolCallingBase(scope: String): String = """
You are the in-app history chat for $scope.

You have retrieval tools for scoped workout-history data. Use them to look up facts before answering: summaries, comparisons, progress, targets, rest, timing, heart-rate context, labels, or practical next steps.

Answer the current user question directly. Use earlier conversation only as follow-up context. If the current question changes topic, follow the new topic.

Your tools cover this chat's scope: $scope, and where the tools expose them, previous sessions of the same workout or the exercise's own history. If the user asks about anything beyond what the tools can retrieve (other workouts, other exercises, or older history), say plainly what is not available and answer with whatever relevant context the tools do provide.

If a claim depends on numbers, the numbers must appear verbatim in retrieved tool output. Do not invent, round, fix, or infer missing numbers.

Be concise by default. For simple questions, use one short paragraph or up to 3 bullets. Do not create a session-by-session breakdown, timeline, or headings unless the user asks for that.

Always answer in complete sentences. Never reply with a bare "?", a single word, or an empty answer — if you cannot retrieve what a question needs, explain that in a full sentence.

If the tools cannot support an answer, say what is missing. Do not give medical advice, diagnoses, or injury treatment.
""".trimIndent()

/** System prompt for history chat when retrieval tools are enabled (no inline export). */
internal fun buildHistoryChatToolCallingSystemPrompt(scope: String): String =
    buildToolEnabledSystemPrompt(buildHistoryChatToolCallingBase(scope))

/**
 * Appends the deterministic always-available facts so the model can discuss the
 * current session even when it fails to call retrieval tools.
 */
internal fun withAlwaysAvailableFacts(systemPrompt: String, coreFactsBlock: String): String =
    if (coreFactsBlock.isBlank()) {
        systemPrompt
    } else {
        systemPrompt + "\n\n--- Known facts about this chat's subject (always available; use tools for detail) ---\n\n" +
            coreFactsBlock.trim()
    }

/**
 * Appends the compacted export once after [instructionsPrompt] (chat instructions only, no history yet).
 */

// The exported history shares the 8K-token context with chat instructions, an
// 8-turn window (12K chars) and the 384-token reply cap; ~12K chars ≈ 4K tokens.
internal const val HISTORY_CHAT_EXPORT_CHAR_BUDGET = 12_000

internal fun buildHistoryChatSystemPromptWithExportedData(
    instructionsPrompt: String,
    toolContext: WorkoutInsightsToolContext,
): String {
    val historyBody = when (toolContext) {
        is WorkoutInsightsToolContext.Exercise ->
            compactExerciseHistoryMarkdown(toolContext.markdown, HISTORY_CHAT_EXPORT_CHAR_BUDGET)
        is WorkoutInsightsToolContext.WorkoutSession ->
            compactWorkoutSessionMarkdown(toolContext.markdown)
    }
    return buildString {
        append(instructionsPrompt.trim())
        append("\n\n--- Exported history (compact, same rules as on-device insights) ---\n\n")
        append(historyBody.trim())
    }
}

/**
 * Prior messages should be ordered oldest-first, and must not include the current user turn.
 */
internal fun buildHistoryChatUserPrompt(
    priorMessages: List<HistoryChatMessage>,
    currentUserContent: String,
    maxConversationChars: Int = HistoryChatLimits.MAX_CONVERSATION_HISTORY_CHARS,
    maxPriorTurns: Int = HistoryChatLimits.MAX_PRIOR_TURNS,
): String {
    val trimmedUser = currentUserContent.trim()
    require(trimmedUser.isNotBlank()) { "User message must not be blank." }

    val boundedMessages = selectConversationWindowMessages(
        messages = priorMessages,
        maxTurns = maxPriorTurns,
        maxChars = maxConversationChars,
        includeAssistantMessages = true,
    )
    val historyBlock = formatConversationWindow(
        priorMessages = boundedMessages,
        maxTurns = Int.MAX_VALUE,
        maxChars = Int.MAX_VALUE,
        includeAssistantMessages = true,
    )

    return buildString {
        appendLine("Answer the current User question below.")
        appendLine("Use earlier conversation only for follow-up context.")
        appendLine()
        if (historyBlock.isNotBlank()) {
            appendLine("Earlier conversation:")
            appendLine(historyBlock)
            appendLine()
        }
        appendLine("User question:")
        append(trimmedUser)
    }
}

/**
 * Formats [priorMessages] (oldest-first) into a bounded transcript for the model prompt.
 * A "turn" is one user message plus the following assistant message (if present).
 */
internal fun formatConversationWindow(
    priorMessages: List<HistoryChatMessage>,
    maxTurns: Int,
    maxChars: Int,
    includeAssistantMessages: Boolean = true,
): String {
    if (priorMessages.isEmpty()) return ""

    val turnBlocks = mutableListOf<String>()
    var pendingUser: HistoryChatMessage? = null
    var turnNumber = 0
    for (message in priorMessages) {
        when (message.role) {
            HistoryChatMessageRole.User -> {
                pendingUser?.let { user ->
                    turnNumber += 1
                    turnBlocks.add(
                        listOf(
                            "Turn $turnNumber",
                            userLine(user.content),
                        ).joinToString("\n")
                    )
                }
                pendingUser = message
            }
            HistoryChatMessageRole.Assistant -> {
                if (!includeAssistantMessages) {
                    pendingUser?.let { user ->
                        turnNumber += 1
                        turnBlocks.add(
                            listOf(
                                "Turn $turnNumber",
                                userLine(user.content),
                            ).joinToString("\n")
                        )
                    }
                    pendingUser = null
                    continue
                }
                val user = pendingUser
                if (user != null) {
                    turnNumber += 1
                    turnBlocks.add(
                        listOf(
                            "Turn $turnNumber",
                            userLine(user.content),
                            assistantLine(message.content),
                        ).joinToString("\n")
                    )
                    pendingUser = null
                } else {
                    turnNumber += 1
                    turnBlocks.add(
                        listOf(
                            "Turn $turnNumber",
                            assistantLine(message.content),
                        ).joinToString("\n")
                    )
                }
            }
        }
    }
    pendingUser?.let {
        turnNumber += 1
        turnBlocks.add(
            listOf(
                "Turn $turnNumber",
                userLine(it.content),
            ).joinToString("\n")
        )
    }

    val selected = turnBlocks.takeLast(maxTurns)
    var joined = selected.joinToString("\n\n")
    if (joined.length > maxChars) {
        joined = joined.takeLast(maxChars).trimStart()
        if (!joined.startsWith("User:") && !joined.startsWith("Assistant:")) {
            joined = "…\n$joined"
        }
    }
    return joined.trim()
}

private fun userLine(content: String): String = "User: ${content.trim()}"

private fun assistantLine(content: String): String = "Assistant: ${content.trim()}"
