package com.gabstra.myworkoutassistant.insights

import org.junit.Assert.assertFalse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class WorkoutHistoryChatPromptBuilderTest {

    @Test
    fun buildHistoryChatUserPrompt_includesQuestionAndPreamble() {
        val prompt = buildHistoryChatUserPrompt(
            priorMessages = emptyList(),
            currentUserContent = "  How did load progress?  ",
        )
        assertTrue(prompt.contains("User question:"))
        assertTrue(prompt.contains("How did load progress?"))
        assertFalse(prompt.contains("system message"))
        assertTrue(prompt.contains("Answer the current User question below."))
        assertTrue(prompt.contains("Use earlier conversation only for follow-up context."))
        assertFalse(prompt.contains("unclear"))
    }

    @Test
    fun buildHistoryChatUserPrompt_includesPriorConversation() {
        val prior = listOf(
            HistoryChatMessage(role = HistoryChatMessageRole.User, content = "First Q"),
            HistoryChatMessage(role = HistoryChatMessageRole.Assistant, content = "First A"),
        )
        val prompt = buildHistoryChatUserPrompt(
            priorMessages = prior,
            currentUserContent = "Follow up",
        )
        assertTrue(prompt.contains("Earlier conversation:"))
        assertTrue(prompt.contains("Turn 1"))
        assertTrue(prompt.contains("User: First Q"))
        assertTrue(prompt.contains("Assistant: First A"))
        assertTrue(prompt.contains("Follow up"))
    }

    @Test
    fun formatConversationWindow_keepsMostRecentTurnsOnly() {
        val messages = listOf(
            HistoryChatMessage(role = HistoryChatMessageRole.User, content = "old u"),
            HistoryChatMessage(role = HistoryChatMessageRole.Assistant, content = "old a"),
            HistoryChatMessage(role = HistoryChatMessageRole.User, content = "new u"),
            HistoryChatMessage(role = HistoryChatMessageRole.Assistant, content = "new a"),
        )
        val window = formatConversationWindow(
            priorMessages = messages,
            maxTurns = 1,
            maxChars = 10_000,
        )
        assertTrue(window.contains("new u"))
        assertTrue(window.contains("new a"))
        assertFalse(window.contains("old u"))
    }

    @Test
    fun formatConversationWindow_truncatesToMaxChars() {
        val long = "x".repeat(500)
        val messages = listOf(
            HistoryChatMessage(role = HistoryChatMessageRole.User, content = long),
            HistoryChatMessage(role = HistoryChatMessageRole.Assistant, content = long),
        )
        val window = formatConversationWindow(
            priorMessages = messages,
            maxTurns = 4,
            maxChars = 200,
        )
        assertTrue(window.length <= 202)
    }

    @Test
    fun selectConversationWindowMessages_keepsNewestWholeTurnsWithinBudget() {
        val messages = listOf(
            HistoryChatMessage(role = HistoryChatMessageRole.User, content = "old question"),
            HistoryChatMessage(role = HistoryChatMessageRole.Assistant, content = "old answer"),
            HistoryChatMessage(role = HistoryChatMessageRole.User, content = "new question"),
            HistoryChatMessage(role = HistoryChatMessageRole.Assistant, content = "new answer"),
            HistoryChatMessage(role = HistoryChatMessageRole.User, content = "latest follow up"),
        )

        val selected = selectConversationWindowMessages(
            messages = messages,
            maxTurns = 3,
            maxChars = "new questionnew answerlatest follow up".length,
        )

        assertEquals(listOf("new question", "new answer", "latest follow up"), selected.map { it.content })
    }

    @Test
    fun buildExerciseHistoryChatSystemPrompt_describesExportedHistoryInSystem() {
        val system = buildExerciseHistoryChatSystemPrompt()
        assertTrue(system.contains("in-app history chat for one exercise"))
        assertTrue(system.contains("Exported history"))
        assertTrue(system.contains("only source of workout facts"))
        assertTrue(system.contains("summaries, comparisons, progress, targets, rest, timing, heart-rate context, labels, or practical next steps"))
        assertTrue(system.contains("Answer the current user question directly"))
        assertTrue(system.contains("Do not invent, round, fix, or infer missing numbers"))
    }

    @Test
    fun buildExerciseHistoryChatSystemPrompt_doesNotMakePlateauFormatUniversal() {
        val system = buildExerciseHistoryChatSystemPrompt()

        assertFalse(system.contains("Output format (strict)"))
        assertFalse(system.contains("Do not switch to plateau/stall analysis"))
        assertFalse(system.contains("Progress-status questions:"))
        assertFalse(system.contains("For advice questions"))
        assertFalse(system.contains("unclear"))
        assertTrue(system.contains("If the current question changes topic, follow the new topic."))
    }

    @Test
    fun buildExerciseHistoryChatSystemPrompt_supportsGenericHistoryQuestions() {
        val system = buildExerciseHistoryChatSystemPrompt()

        assertTrue(system.contains("The user may ask anything about that history"))
        assertTrue(system.contains("Use whatever exported fields are relevant to the question"))
    }

    @Test
    fun buildWorkoutSessionHistoryChatSystemPrompt_describesExportedHistoryInSystem() {
        val system = buildWorkoutSessionHistoryChatSystemPrompt()
        assertTrue(system.contains("one completed workout session"))
        assertTrue(system.contains("The user may ask anything about that history"))
        assertTrue(system.contains("Answer the current user question directly"))
        assertTrue(system.contains("Use whatever exported fields are relevant to the question"))
    }

    @Test
    fun buildHistoryChatSystemPromptWithExportedData_compactsExerciseMarkdownExport() {
        val exportedMarkdown = """
            # Bench Press
            Sessions: 2 | Range: 2026-01-01 to 2026-01-10

            ## S1: 2026-01-01 09:00 | Push A
            Session: start at 2026-01-01T09:00 | sessionId: abc123
            #### Progression Context
            - State: PROGRESS
        """.trimIndent()

        val system = buildHistoryChatSystemPromptWithExportedData(
            instructionsPrompt = buildExerciseHistoryChatSystemPrompt(),
            toolContext = WorkoutInsightsToolContext.Exercise(
                title = "Bench chat",
                exerciseName = "Bench Press",
                markdown = exportedMarkdown,
            ),
        )

        // The exercise export goes through the standard compactor (session
        // metadata lines are pruned; compact session headers and progression
        // sections survive in the normalized compact format).
        assertTrue(
            "ACTUAL SYSTEM PROMPT:\n$system",
            system.contains("S1 2026-01-01 09:00 | Push A"),
        )
        assertTrue(system.contains("PROG State: PROGRESS"))
    }

    @Test
    fun buildHistoryChatSystemPromptWithExportedData_boundsOversizedExerciseExport() {
        val sessions = (1..40).joinToString("\n\n") { index ->
            """
            ## S$index: 2026-01-01 09:00 | Push A
            ${"Detail line for session $index. "}
            ${"- Set line with load and reps ".repeat(20)}
            """.trimIndent()
        }
        val exportedMarkdown = "# Bench Press\nSessions: 40\n\n$sessions"
        val instructions = buildExerciseHistoryChatSystemPrompt()

        val system = buildHistoryChatSystemPromptWithExportedData(
            instructionsPrompt = instructions,
            toolContext = WorkoutInsightsToolContext.Exercise(
                title = "Bench chat",
                exerciseName = "Bench Press",
                markdown = exportedMarkdown,
            ),
        )

        // The export must stay bounded inside the shared 8K-token context even
        // for very long histories, while remaining session-shaped.
        assertTrue(system.length < instructions.length + HISTORY_CHAT_EXPORT_CHAR_BUDGET + 500)
        assertFalse(system.contains("Detail line for session 40."))
        assertTrue(system.contains("## S7: 2026-01-01 09:00 | Push A"))
    }
}
