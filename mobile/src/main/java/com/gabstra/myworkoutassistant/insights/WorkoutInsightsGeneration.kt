package com.gabstra.myworkoutassistant.insights

internal const val FINAL_SYNTHESIS_PLACEHOLDER = "Generating final insight..."
internal const val PREPARING_TOOLS_PLACEHOLDER = "Preparing insight context..."
internal const val CHART_ANALYSIS_DISABLED_PLACEHOLDER = PREPARING_TOOLS_PLACEHOLDER
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
)

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
    val finalSynthesisBasePrompt = buildFinalSynthesisInlinePrompt(request)
    emitChunk(
        WorkoutInsightsChunk(
            title = request.title,
            text = PREPARING_TOOLS_PLACEHOLDER,
            phase = WorkoutInsightsPhase.PREPARING_TOOLS,
            statusText = "Preparing insight context..."
        )
    )
    val finalPrompt = finalSynthesisBasePrompt

    logWorkoutInsightsBlock(logTag, "${transportLabel}_final_prompt", finalPrompt)
    val accumulated = StringBuilder()
    streamText(
        WorkoutInsightsTransportRequest(
            systemPrompt = buildFinalSynthesisSystemPrompt(request),
            prompt = finalPrompt,
            imagePngBytes = null,
            toolContext = null,
            requestLogLabel = "${transportLabel}_final_request",
            responseLogLabel = "${transportLabel}_final_raw_response",
        ),
        { chunk ->
            accumulated.append(chunk)
            emitChunk(
                WorkoutInsightsChunk(
                    title = request.title,
                    text = accumulated.toString(),
                    phase = WorkoutInsightsPhase.FINAL_SYNTHESIS,
                    statusText = "Generating final insight..."
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
                            WorkoutInsightsPhase.CHART_ANALYSIS -> CHART_ANALYSIS_DISABLED_PLACEHOLDER
                            WorkoutInsightsPhase.FINAL_SYNTHESIS -> FINAL_SYNTHESIS_PLACEHOLDER
                        }
                    },
                    phase = phase,
                    statusText = statusText
                )
            )
        }
    )
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
                statusText = "Generating final insight..."
            )
        )
    }
    onAfterChartAnalysis?.invoke()
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
    return when (request.toolContext) {
        is WorkoutInsightsToolContext.Exercise -> EXERCISE_INSIGHTS_SYSTEM_PROMPT.trimIndent()
        is WorkoutInsightsToolContext.WorkoutSession -> WORKOUT_INSIGHTS_SYSTEM_PROMPT.trimIndent()
        null -> request.systemPrompt.trimIndent()
    }
}
