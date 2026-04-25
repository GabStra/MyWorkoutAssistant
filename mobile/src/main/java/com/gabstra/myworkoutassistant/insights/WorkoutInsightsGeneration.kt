package com.gabstra.myworkoutassistant.insights

internal const val FINAL_SYNTHESIS_PLACEHOLDER = "Generating insight..."
internal const val PREPARING_TOOLS_PLACEHOLDER = "Loading insight model..."
private const val HEART_RATE_CHART_ANALYSIS_SYSTEM_PROMPT_BASE = """
You are extracting observational context from an attached workout session heart-rate chart.
Use only what is clearly visible in the chart.
Do not estimate numeric heart-rate ranges from the chart.
Do not infer workout quality, pacing problems, poor recovery, or fatigue unless the chart clearly shows progressive drift or declining repeatability.
Variability alone is not evidence of a problem.
Prefer descriptive shape observations over coaching advice.
If a visible feature would be clearer with session labels, investigate with the available timeline tool instead of guessing.
When the chart appears to have repeated peaks, distinct phases, or a possible late-session change, prefer at least one targeted timeline lookup before finalizing.
Return plain text with up to 4 lines total:
SUMMARY: ...
SUMMARY: ...
SIGNAL: ...
SIGNAL: ...
Do not use markdown headings, bullets, or extra prose.
"""

private const val HEART_RATE_CHART_ANALYSIS_TIMELINE_TOOL_SYSTEM_BLOCK = """
Session timeline tool:
- Tool name: get_session_timeline_for_time_range.
- Arguments: start_seconds and end_seconds (inclusive, elapsed seconds from workout start); returns session blocks overlapping that window.
- Purpose: attach exercise, rest, transition, lead-in, or wrap-up labels to a visible heart-rate pattern.
- Investigate visible peaks, clusters, phase changes, or ambiguous late-session behavior with targeted windows instead of unlabeled chart wording alone.
- If repeated features or distinct phases are visible, prefer at least one tool call before finalizing.
- Default: chart-shape wording alone only when the visible pattern is already clear without labels.
"""

internal fun buildHeartRateChartAnalysisSystemPrompt(
    hasSessionTimelineTool: Boolean,
): String = buildString {
    append(HEART_RATE_CHART_ANALYSIS_SYSTEM_PROMPT_BASE.trimIndent())
    if (hasSessionTimelineTool) {
        append("\n\n")
        append(HEART_RATE_CHART_ANALYSIS_TIMELINE_TOOL_SYSTEM_BLOCK.trimIndent())
    }
}

internal data class WorkoutInsightsTransportRequest(
    val systemPrompt: String,
    val prompt: String,
    val imagePngBytes: ByteArray?,
    val toolContext: WorkoutInsightsToolContext?,
    val chartTimelineToolContext: WorkoutInsightsChartTimelineContext? = null,
    val requestLogLabel: String,
    val responseLogLabel: String,
    /**
     * When set, caps generated tokens for this request (LiteRT: decode limit; OpenAI-compatible:
     * `max_completion_tokens`). Null leaves the backend default (full insight generations).
     */
    val maxOutputTokens: Int? = null,
)

private const val MAX_FINAL_SYNTHESIS_ATTEMPTS = 2
private const val REPEATED_TEXT_RESTART_STATUS = "Repeated text detected. Restarting insight generation..."
private const val REPEATED_TEXT_RETRY_SYSTEM_INSTRUCTION = """
The previous generation was stopped because it began repeating text.
Regenerate the insight from scratch. Keep each idea once, do not repeat sentences or clauses, and finish concisely.
"""

private class RepeatedInsightTextException(
    val result: InsightRepetitionResult,
) : RuntimeException("Repeated insight text detected: ${result.reason}")

internal suspend fun runWorkoutInsightsGeneration(
    request: WorkoutInsightsRequest,
    logTag: String,
    transportLabel: String,
    emitChunk: suspend (WorkoutInsightsChunk) -> Unit,
    generateText: suspend (WorkoutInsightsTransportRequest) -> String,
    streamText: suspend (
        transportRequest: WorkoutInsightsTransportRequest,
        onChunk: suspend (String) -> Unit,
        onProgress: suspend (WorkoutInsightsPhase, String) -> Unit,
    ) -> Unit,
    onAfterChartAnalysis: (suspend () -> Unit)? = null,
) {
    if (request.useTransportToolCalling && request.toolContext != null) {
        emitChunk(
            WorkoutInsightsChunk(
                title = request.title,
                text = PREPARING_TOOLS_PLACEHOLDER,
                phase = WorkoutInsightsPhase.PREPARING_TOOLS,
                statusText = PREPARING_TOOLS_PLACEHOLDER
            )
        )
        val chatSystemPrompt = appendCustomInsightInstructions(
            systemPrompt = request.systemPrompt.trimIndent(),
            customInstructions = request.customInstructions
        )
        logWorkoutInsightsBlock(logTag, "${transportLabel}_chat_system_prompt", chatSystemPrompt)
        logWorkoutInsightsBlock(logTag, "${transportLabel}_chat_user_prompt", request.prompt)
        val accumulated = StringBuilder()
        var finalAttempt = 1
        while (true) {
            val repetitionDetector = InsightRepetitionDetector()
            try {
                streamText(
                    WorkoutInsightsTransportRequest(
                        systemPrompt = chatSystemPrompt.withRepeatedTextRetryInstruction(finalAttempt),
                        prompt = request.prompt,
                        imagePngBytes = null,
                        toolContext = request.toolContext,
                        chartTimelineToolContext = null,
                        requestLogLabel = "${transportLabel}_chat_request".withAttemptLogSuffix(finalAttempt),
                        responseLogLabel = "${transportLabel}_chat_raw_response".withAttemptLogSuffix(finalAttempt),
                        maxOutputTokens = HistoryChatLimits.MAX_OUTPUT_TOKENS,
                    ),
                    { chunk ->
                        accumulated.append(chunk)
                        repetitionDetector.detect(accumulated.toString())?.let { result ->
                            throw RepeatedInsightTextException(result)
                        }
                        emitChunk(
                            WorkoutInsightsChunk(
                                title = request.title,
                                text = accumulated.toString(),
                                phase = WorkoutInsightsPhase.FINAL_SYNTHESIS,
                                statusText = FINAL_SYNTHESIS_PLACEHOLDER
                            )
                        )
                    },
                    { phase, statusText ->
                        emitChunk(
                            WorkoutInsightsChunk(
                                title = request.title,
                                text = accumulated.toString().ifBlank {
                                    when (phase) {
                                        WorkoutInsightsPhase.PREPARING_TOOLS -> PREPARING_TOOLS_PLACEHOLDER
                                        WorkoutInsightsPhase.FETCHING_CONTEXT -> statusText
                                        WorkoutInsightsPhase.SUMMARIZING_CONTEXT -> statusText
                                        WorkoutInsightsPhase.CHART_ANALYSIS -> statusText.ifBlank { FINAL_SYNTHESIS_PLACEHOLDER }
                                        WorkoutInsightsPhase.FINAL_SYNTHESIS -> FINAL_SYNTHESIS_PLACEHOLDER
                                    }
                                },
                                phase = phase,
                                statusText = statusText
                            )
                        )
                    }
                )
                break
            } catch (exception: RepeatedInsightTextException) {
                logWorkoutInsightsBlock(
                    logTag,
                    "${transportLabel}_chat_repeated_text_attempt_$finalAttempt",
                    buildRepeatedTextLog(
                        partialText = accumulated.toString(),
                        result = exception.result
                    )
                )
                if (finalAttempt >= MAX_FINAL_SYNTHESIS_ATTEMPTS) {
                    throw IllegalStateException(
                        "Chat generation repeated text after retry. Please try again."
                    )
                }
                finalAttempt += 1
                accumulated.clear()
                emitChunk(
                    WorkoutInsightsChunk(
                        title = request.title,
                        text = REPEATED_TEXT_RESTART_STATUS,
                        phase = WorkoutInsightsPhase.FINAL_SYNTHESIS,
                        statusText = REPEATED_TEXT_RESTART_STATUS
                    )
                )
            }
        }
        val rawReply = accumulated.toString()
        logWorkoutInsightsBlock(
            logTag,
            "${transportLabel}_chat_final_raw_response",
            rawReply.ifBlank { "No reply was generated." }
        )
        val normalizedReply = postProcessInsightMarkdown(
            markdown = rawReply,
            toolContext = request.toolContext,
            evidencePrompt = request.prompt
        )
        if (normalizedReply != rawReply) {
            logWorkoutInsightsBlock(
                logTag,
                "${transportLabel}_chat_final_postprocessed_response",
                normalizedReply.ifBlank { "No reply was generated." }
            )
            accumulated.clear()
            accumulated.append(normalizedReply)
            emitChunk(
                WorkoutInsightsChunk(
                    title = request.title,
                    text = normalizedReply,
                    phase = WorkoutInsightsPhase.FINAL_SYNTHESIS,
                    statusText = FINAL_SYNTHESIS_PLACEHOLDER
                )
            )
        }
        onAfterChartAnalysis?.invoke()
        return
    }

    val finalSynthesisBasePrompt = if (request.historyChatSystemIncludesData && request.toolContext != null) {
        request.prompt
    } else {
        buildFinalSynthesisInlinePrompt(request)
    }
    emitChunk(
        WorkoutInsightsChunk(
            title = request.title,
            text = PREPARING_TOOLS_PLACEHOLDER,
            phase = WorkoutInsightsPhase.PREPARING_TOOLS,
            statusText = PREPARING_TOOLS_PLACEHOLDER
        )
    )
    val finalPrompt = finalSynthesisBasePrompt

    logWorkoutInsightsBlock(logTag, "${transportLabel}_final_prompt", finalPrompt)
    val accumulated = StringBuilder()
    var finalAttempt = 1
    while (true) {
        val repetitionDetector = InsightRepetitionDetector()
        try {
            val synthesisSystemPrompt = if (request.historyChatSystemIncludesData && request.toolContext != null) {
                appendCustomInsightInstructions(
                    systemPrompt = request.systemPrompt.trimIndent(),
                    customInstructions = request.customInstructions,
                )
            } else {
                buildFinalSynthesisSystemPrompt(request)
            }
            streamText(
                WorkoutInsightsTransportRequest(
                    systemPrompt = synthesisSystemPrompt
                        .withRepeatedTextRetryInstruction(finalAttempt),
                    prompt = finalPrompt,
                    imagePngBytes = null,
                    toolContext = null,
                    requestLogLabel = "${transportLabel}_final_request".withAttemptLogSuffix(finalAttempt),
                    responseLogLabel = "${transportLabel}_final_raw_response".withAttemptLogSuffix(finalAttempt),
                    maxOutputTokens = if (request.historyChatSystemIncludesData) {
                        HistoryChatLimits.MAX_OUTPUT_TOKENS
                    } else {
                        null
                    },
                ),
                { chunk ->
                    accumulated.append(chunk)
                    repetitionDetector.detect(accumulated.toString())?.let { result ->
                        throw RepeatedInsightTextException(result)
                    }
                    emitChunk(
                        WorkoutInsightsChunk(
                            title = request.title,
                            text = accumulated.toString(),
                            phase = WorkoutInsightsPhase.FINAL_SYNTHESIS,
                            statusText = FINAL_SYNTHESIS_PLACEHOLDER
                        )
                    )
                },
                { phase, statusText ->
                    emitChunk(
                        WorkoutInsightsChunk(
                            title = request.title,
                            text = accumulated.toString().ifBlank {
                                when (phase) {
                                    WorkoutInsightsPhase.PREPARING_TOOLS -> PREPARING_TOOLS_PLACEHOLDER
                                    WorkoutInsightsPhase.FETCHING_CONTEXT -> statusText
                                    WorkoutInsightsPhase.SUMMARIZING_CONTEXT -> statusText
                                    WorkoutInsightsPhase.CHART_ANALYSIS -> statusText.ifBlank { FINAL_SYNTHESIS_PLACEHOLDER }
                                    WorkoutInsightsPhase.FINAL_SYNTHESIS -> FINAL_SYNTHESIS_PLACEHOLDER
                                }
                            },
                            phase = phase,
                            statusText = statusText
                        )
                    )
                }
            )
            break
        } catch (exception: RepeatedInsightTextException) {
            logWorkoutInsightsBlock(
                logTag,
                "${transportLabel}_final_repeated_text_attempt_$finalAttempt",
                buildRepeatedTextLog(
                    partialText = accumulated.toString(),
                    result = exception.result
                )
            )
            if (finalAttempt >= MAX_FINAL_SYNTHESIS_ATTEMPTS) {
                throw IllegalStateException(
                    "Insight generation repeated text after retry. Please try again."
                )
            }
            finalAttempt += 1
            accumulated.clear()
            emitChunk(
                WorkoutInsightsChunk(
                    title = request.title,
                    text = REPEATED_TEXT_RESTART_STATUS,
                    phase = WorkoutInsightsPhase.FINAL_SYNTHESIS,
                    statusText = REPEATED_TEXT_RESTART_STATUS
                )
            )
        }
    }
    val rawInsight = accumulated.toString()
    logWorkoutInsightsBlock(
        logTag,
        "${transportLabel}_final_raw_response",
        rawInsight.ifBlank { "No insights were generated." }
    )
    val normalizedInsight = postProcessInsightMarkdown(
        markdown = rawInsight,
        toolContext = request.toolContext,
        evidencePrompt = finalPrompt
    )
    if (normalizedInsight != rawInsight) {
        logWorkoutInsightsBlock(
            logTag,
            "${transportLabel}_final_postprocessed_response",
            normalizedInsight.ifBlank { "No insights were generated." }
        )
        accumulated.clear()
        accumulated.append(normalizedInsight)
        emitChunk(
            WorkoutInsightsChunk(
                title = request.title,
                text = normalizedInsight,
                phase = WorkoutInsightsPhase.FINAL_SYNTHESIS,
                statusText = FINAL_SYNTHESIS_PLACEHOLDER
            )
        )
    }
    onAfterChartAnalysis?.invoke()
}

private fun String.withAttemptLogSuffix(
    attempt: Int,
): String = if (attempt == 1) this else "${this}_retry_$attempt"

private fun String.withRepeatedTextRetryInstruction(
    attempt: Int,
): String {
    if (attempt == 1) return this
    return listOf(
        trimEnd(),
        REPEATED_TEXT_RETRY_SYSTEM_INSTRUCTION.trimIndent()
    ).joinToString("\n\n")
}

private fun buildRepeatedTextLog(
    partialText: String,
    result: InsightRepetitionResult,
): String = buildString {
    appendLine("Reason: ${result.reason}")
    appendLine("Repeated text: ${result.repeatedText}")
    appendLine()
    append(partialText.ifBlank { "<empty>" })
}

internal fun buildFinalSynthesisInlinePrompt(
    request: WorkoutInsightsRequest,
): String {
    return when (val toolContext = request.toolContext) {
        is WorkoutInsightsToolContext.Exercise -> buildExercisePrompt(toolContext.markdown)
        is WorkoutInsightsToolContext.WorkoutSession -> buildWorkoutSessionPrompt(
            markdown = toolContext.markdown,
            workoutCategoryGuidance = "",
            workoutCategoryLine = "",
        )
        null -> request.prompt
    }
}

internal fun buildFinalSynthesisSystemPrompt(
    request: WorkoutInsightsRequest,
): String {
    val basePrompt = when (request.toolContext) {
        is WorkoutInsightsToolContext.Exercise -> EXERCISE_INSIGHTS_SYSTEM_PROMPT.trimIndent()
        is WorkoutInsightsToolContext.WorkoutSession -> WORKOUT_INSIGHTS_SYSTEM_PROMPT.trimIndent()
        null -> request.systemPrompt.trimIndent()
    }
    return appendCustomInsightInstructions(
        systemPrompt = basePrompt,
        customInstructions = request.customInstructions
    )
}

private fun appendCustomInsightInstructions(
    systemPrompt: String,
    customInstructions: String,
): String {
    val normalizedInstructions = customInstructions
        .trim()
        .takeIf { it.isNotBlank() }
        ?: return systemPrompt
    return listOf(
        systemPrompt.trimEnd(),
        """
        User insight preferences:
        Follow these additional user-provided instructions when they do not conflict with the evidence, safety rules, or required output format:
        $normalizedInstructions
        """.trimIndent()
    ).joinToString("\n\n")
}
