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

/**
 * Appends the compacted export once after [instructionsPrompt] (chat instructions only, no history yet).
 */
internal fun buildHistoryChatSystemPromptWithExportedData(
    instructionsPrompt: String,
    toolContext: WorkoutInsightsToolContext,
): String {
    val historyBody = when (toolContext) {
        is WorkoutInsightsToolContext.Exercise ->
            toolContext.markdown
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

    val historyBlock = formatConversationWindow(
        priorMessages = priorMessages,
        maxTurns = maxPriorTurns,
        maxChars = maxConversationChars,
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
