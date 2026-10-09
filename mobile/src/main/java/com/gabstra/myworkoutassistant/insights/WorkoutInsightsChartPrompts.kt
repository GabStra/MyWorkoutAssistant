package com.gabstra.myworkoutassistant.insights

internal fun buildHeartRateChartAwarePrompt(prompt: String): String = buildString {
    append(stripRedundantHeartRateTextMetrics(prompt).trimEnd())
    append("\n\nAttached image context:\n")
    append("- The attached image is the workout session heart-rate chart.\n")
    append("- Use it to understand shape, peaks, drift, and recovery timing.\n")
    append("- Prefer explicit text metrics over conflicting image cues.\n")
}

internal fun stripRedundantHeartRateTextMetrics(
    prompt: String,
): String = prompt
    .lineSequence()
    .filterNot { line ->
        line.trimStart().startsWith("HR ")
    }
    .joinToString("\n")

internal fun buildHeartRateChartImageOnlyPrompt(
    chartAnalysisContext: String? = null,
    chartTimelineToolContext: WorkoutInsightsChartTimelineContext? = null,
): String = buildString {
    appendLine("Analyze the attached workout session heart-rate chart only.")
    appendLine("Use only what is visible in the chart and any timeline context explicitly provided below.")
    appendLine("Do not infer workout quality, fatigue, exercise type, or performance from the chart alone.")
    appendLine("Do not estimate exact bpm values, intensity zones, or exact recovery durations from the image.")
    appendLine("If the image is unclear or the pattern is ambiguous, say so plainly.")

    when {
        chartTimelineToolContext != null -> {
            appendLine()
            appendLine("Session duration: ${chartTimelineToolContext.durationSeconds} seconds from start to end.")
            appendLine(
                "Tool available: get_session_timeline_for_time_range(start_seconds, end_seconds), " +
                        "using inclusive elapsed seconds from workout start."
            )
            appendLine(
                "Use the tool only when visible features would be materially clearer with block names or timing, " +
                        "especially repeated peaks, phase changes, long recoveries, or late-session changes."
            )
            appendLine(
                "If the chart appears to contain repeated peaks or distinct phases, prefer at least one targeted tool call before finalizing."
            )
            appendLine("If tool output conflicts with the chart, trust the chart.")
        }

        else -> {
            chartAnalysisContext
                ?.trim()
                ?.takeIf { it.isNotBlank() }
                ?.let { context ->
                    appendLine()
                    appendLine("Provided timeline context (elapsed time from workout start; contiguous blocks):")
                    appendLine(context)
                    appendLine("Use it only to align visible features with likely work, rest, or transition periods.")
                    appendLine("If the pasted timeline conflicts with the chart, trust the chart.")
                }
        }
    }

    appendLine()
    appendLine("Focus only on chart-supported observations such as:")
    appendLine("- overall pattern: steady, intermittent, phased, or unclear")
    appendLine("- repeatability of visible peaks: similar, fading, building, or unclear")
    appendLine("- recovery shape between peaks: clear drop, partial drop, or unclear")
    appendLine("- late-session behavior: upward drift, stable pattern, reduced peaks, or unclear")
    appendLine("- obvious transitions: warm-up-like rise, repeated work/rest cycles, cooldown-like fall, or unclear")

    appendLine()
    appendLine("Output requirements:")
    appendLine("- keep the analysis concise and practical")
    appendLine("- report only observations that are visually supported")
    appendLine("- prefer cautious wording when evidence is mixed")
    append("- do not restate timeline context unless it changes the interpretation")
}

internal fun buildPromptWithHeartRateChartAnalysis(
    prompt: String,
    chartAnalysis: String?,
    supportingMarkdown: String? = null,
): String = buildString {
    append(prompt.trimEnd())
    formatHeartRateChartAnalysisForPrompt(
        chartAnalysis = chartAnalysis,
        supportingMarkdown = supportingMarkdown
    )?.let {
        append("\n\nHeart-rate chart observations:\n")
        append(it)
        append("\n\nTreat chart observations as secondary context for the final insight.")
        append("\nPrefer explicit workout metrics over conflicting chart observation wording.")
        append("\nDo not let chart wording override plan, previous, or best-to-date comparisons.")
    }
}

internal fun formatHeartRateChartAnalysisForPrompt(
    chartAnalysis: String?,
    supportingMarkdown: String? = null,
): String? {
    val raw = chartAnalysis?.takeUnless { it.isBlank() || it == "No insights were generated." } ?: return null
    val sanitized = sanitizeInsightMarkdown(normalizeChartAnalysisTokens(raw))
    val structuredMetrics = parseStructuredHeartRateMetrics(supportingMarkdown)
    val structuredLines = mutableListOf<String>()
    var currentPrefix = "CHART NOTE"

    sanitized.lineSequence()
        .map(String::trim)
        .filter { it.isNotBlank() }
        .forEach { line ->
            when {
                line.equals("## Chart Summary", ignoreCase = true) -> currentPrefix = "CHART SUMMARY"
                line.equals("## Chart Signals", ignoreCase = true) -> currentPrefix = "CHART SIGNAL"
                line.startsWith("SUMMARY:", ignoreCase = true) ->
                    structuredLines += "CHART SUMMARY ${line.substringAfter(':').trim()}"
                line.startsWith("SIGNAL:", ignoreCase = true) ->
                    structuredLines += "CHART SIGNAL ${line.substringAfter(':').trim()}"
                line.startsWith("- ") ->
                    structuredLines += "$currentPrefix ${line.removePrefix("- ").trim()}"
                else -> structuredLines += "$currentPrefix $line"
            }
        }

    return structuredLines
        .map { it.replace(Regex("\\s+"), " ").trim() }
        .filter { it.length > "CHART NOTE ".length }
        .filterNot(::isUnreliableChartMetricLine)
        .filter { chartLine -> isChartLineConsistentWithMetrics(chartLine, structuredMetrics) }
        .distinct()
        .take(4)
        .takeIf { it.isNotEmpty() }
        ?.joinToString("\n")
}

private fun normalizeChartAnalysisTokens(
    chartAnalysis: String,
): String {
    return chartAnalysis.replace(
        Regex("""(?i)(?<=.)(?=(?:SUMMARY:|SIGNAL:|##\s*Chart\s+Summary|##\s*Chart\s+Signals))"""),
        "\n"
    )
}

private data class StructuredHeartRateMetrics(
    val avgPercentMaxHr: Int?,
    val peakPercentMaxHr: Int?,
    val highIntensityExposurePercent: Int?,
)

private fun parseStructuredHeartRateMetrics(
    markdown: String?,
): StructuredHeartRateMetrics {
    val source = markdown.orEmpty()
    return StructuredHeartRateMetrics(
        avgPercentMaxHr = Regex("""Avg % max HR:\s*(\d{1,3})%""", RegexOption.IGNORE_CASE)
            .find(source)
            ?.groupValues
            ?.getOrNull(1)
            ?.toIntOrNull(),
        peakPercentMaxHr = Regex("""Peak % max HR:\s*(\d{1,3})%""", RegexOption.IGNORE_CASE)
            .find(source)
            ?.groupValues
            ?.getOrNull(1)
            ?.toIntOrNull(),
        highIntensityExposurePercent =
            Regex("""High-intensity exposure:\s*(\d{1,3})%""", RegexOption.IGNORE_CASE)
                .find(source)
                ?.groupValues
                ?.getOrNull(1)
                ?.toIntOrNull(),
    )
}

private fun isUnreliableChartMetricLine(
    line: String,
): Boolean {
    val normalized = line.lowercase()
    return normalized.contains(" bpm") ||
        normalized.contains("between approximately") ||
        normalized.contains("between ") ||
        normalized.contains("high-intensity") ||
        normalized.contains("high heart rate") ||
        normalized.contains("shorter towards the end") ||
        normalized.contains("longer towards the end") ||
        normalized.contains("recoveries appear")
}

private fun isChartLineConsistentWithMetrics(
    line: String,
    metrics: StructuredHeartRateMetrics,
): Boolean {
    val normalized = line.lowercase()
    if (
        metrics.highIntensityExposurePercent == 0 &&
        metrics.peakPercentMaxHr != null &&
        metrics.peakPercentMaxHr <= 80 &&
        (normalized.contains("high-intensity") || normalized.contains("high heart rate"))
    ) {
        return false
    }
    return true
}
