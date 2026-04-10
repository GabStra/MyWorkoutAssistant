package com.gabstra.myworkoutassistant.insights

import android.util.Log

internal const val CHART_ANALYSIS_PLACEHOLDER = "Analyzing heart-rate chart..."
internal const val FINAL_SYNTHESIS_PLACEHOLDER = "Combining chart analysis with workout data..."
internal const val PREPARING_TOOLS_PLACEHOLDER = "Preparing insight tools..."
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
    val finalPrompt = if (request.imagePngBytes != null) {
        emitChunk(
            WorkoutInsightsChunk(
                title = request.title,
                text = CHART_ANALYSIS_PLACEHOLDER,
                phase = WorkoutInsightsPhase.CHART_ANALYSIS,
                statusText = "Step 1: Analyzing heart-rate chart..."
            )
        )
        val chartAnalysisPrompt = buildHeartRateChartImageOnlyPrompt(
            chartAnalysisContext = request.chartAnalysisContext,
            chartTimelineToolContext = request.chartTimelineToolContext,
        )
        Log.d(logTag, "${transportLabel}_chart_analysis_prompt_start\n$chartAnalysisPrompt\n${transportLabel}_chart_analysis_prompt_end")
        val chartAnalysis = runCatching {
            generateText(
                WorkoutInsightsTransportRequest(
                    systemPrompt = buildHeartRateChartAnalysisSystemPrompt(
                        hasSessionTimelineTool = request.chartTimelineToolContext != null,
                    ),
                    prompt = chartAnalysisPrompt,
                    imagePngBytes = request.imagePngBytes,
                    toolContext = null,
                    chartTimelineToolContext = request.chartTimelineToolContext,
                    requestLogLabel = "${transportLabel}_chart_analysis_request",
                    responseLogLabel = "${transportLabel}_chart_analysis_raw_response",
                )
            )
        }.onFailure { throwable ->
            Log.w(logTag, "${transportLabel}_chart_analysis_failed_falling_back_to_text", throwable)
        }.getOrNull()

        onAfterChartAnalysis?.invoke()
        emitChunk(
            WorkoutInsightsChunk(
                title = request.title,
                text = FINAL_SYNTHESIS_PLACEHOLDER,
                phase = WorkoutInsightsPhase.FINAL_SYNTHESIS,
                statusText = "Step 2: Generating final insight..."
            )
        )
        buildPromptWithHeartRateChartAnalysis(
            prompt = request.prompt,
            chartAnalysis = chartAnalysis,
            supportingMarkdown = request.toolContext?.markdown
        )
    } else {
        emitChunk(
            WorkoutInsightsChunk(
                title = request.title,
                text = PREPARING_TOOLS_PLACEHOLDER,
                phase = WorkoutInsightsPhase.PREPARING_TOOLS,
                statusText = "Preparing insight tools..."
            )
        )
        request.prompt
    }

    Log.d(logTag, "${transportLabel}_final_prompt_start\n$finalPrompt\n${transportLabel}_final_prompt_end")
    val accumulated = StringBuilder()
    streamText(
        WorkoutInsightsTransportRequest(
            systemPrompt = request.systemPrompt.trimIndent(),
            prompt = finalPrompt,
            imagePngBytes = null,
            toolContext = request.toolContext,
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
                            WorkoutInsightsPhase.CHART_ANALYSIS -> CHART_ANALYSIS_PLACEHOLDER
                            WorkoutInsightsPhase.FINAL_SYNTHESIS -> FINAL_SYNTHESIS_PLACEHOLDER
                        }
                    },
                    phase = phase,
                    statusText = statusText
                )
            )
        }
    )
    val normalizedInsight = postProcessInsightMarkdown(
        markdown = accumulated.toString(),
        toolContext = request.toolContext
    )
    if (normalizedInsight != accumulated.toString()) {
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
    if (request.toolContext == null) {
        Log.d(
            logTag,
            "${transportLabel}_final_raw_response_start\n${accumulated.toString().ifBlank { "No insights were generated." }}\n${transportLabel}_final_raw_response_end"
        )
    }
}
