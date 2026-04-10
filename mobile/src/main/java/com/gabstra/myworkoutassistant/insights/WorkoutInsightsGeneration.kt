package com.gabstra.myworkoutassistant.insights

import android.util.Log

internal const val CHART_ANALYSIS_PLACEHOLDER = "Analyzing heart-rate chart..."
internal const val FINAL_SYNTHESIS_PLACEHOLDER = "Combining chart analysis with workout data..."
internal const val HEART_RATE_CHART_ANALYSIS_SYSTEM_PROMPT = """
You are extracting observational context from an attached workout session heart-rate chart.
Use only what is clearly visible in the chart.
Do not invent precise numbers that are not visually clear.
Do not infer workout quality, pacing problems, poor recovery, or fatigue unless the chart clearly shows progressive drift, shrinking recoveries, or declining repeatability.
Variability alone is not evidence of a problem.
Prefer descriptive observations over coaching advice.
Return plain text with up to 4 lines total:
SUMMARY: ...
SUMMARY: ...
SIGNAL: ...
SIGNAL: ...
Do not use markdown headings, bullets, or extra prose.
"""

internal data class WorkoutInsightsTransportRequest(
    val systemPrompt: String,
    val prompt: String,
    val imagePngBytes: ByteArray?,
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
    ) -> Unit,
    onAfterChartAnalysis: (suspend () -> Unit)? = null,
) {
    val finalPrompt = if (request.imagePngBytes != null) {
        emitChunk(
            WorkoutInsightsChunk(
                title = request.title,
                text = CHART_ANALYSIS_PLACEHOLDER,
                phase = WorkoutInsightsPhase.CHART_ANALYSIS,
            )
        )
        val chartAnalysisPrompt = buildHeartRateChartImageOnlyPrompt()
        Log.d(logTag, "${transportLabel}_chart_analysis_prompt_start\n$chartAnalysisPrompt\n${transportLabel}_chart_analysis_prompt_end")
        val chartAnalysis = runCatching {
            generateText(
                WorkoutInsightsTransportRequest(
                    systemPrompt = HEART_RATE_CHART_ANALYSIS_SYSTEM_PROMPT.trimIndent(),
                    prompt = chartAnalysisPrompt,
                    imagePngBytes = request.imagePngBytes,
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
            )
        )
        buildPromptWithHeartRateChartAnalysis(request.prompt, chartAnalysis)
    } else {
        request.prompt
    }

    Log.d(logTag, "${transportLabel}_final_prompt_start\n$finalPrompt\n${transportLabel}_final_prompt_end")
    val accumulated = StringBuilder()
    streamText(
        WorkoutInsightsTransportRequest(
            systemPrompt = request.systemPrompt.trimIndent(),
            prompt = finalPrompt,
            imagePngBytes = null,
            requestLogLabel = "${transportLabel}_final_request",
            responseLogLabel = "${transportLabel}_final_raw_response",
        )
    ) { chunk ->
        accumulated.append(chunk)
        emitChunk(
            WorkoutInsightsChunk(
                title = request.title,
                text = accumulated.toString(),
                phase = WorkoutInsightsPhase.FINAL_SYNTHESIS,
            )
        )
    }
    onAfterChartAnalysis?.invoke()
    Log.d(
        logTag,
        "${transportLabel}_final_raw_response_start\n${accumulated.toString().ifBlank { "No insights were generated." }}\n${transportLabel}_final_raw_response_end"
    )
}
