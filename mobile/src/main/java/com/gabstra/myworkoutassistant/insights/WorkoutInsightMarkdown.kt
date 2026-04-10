package com.gabstra.myworkoutassistant.insights

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.TextStyle
import dev.jeziellago.compose.markdowntext.MarkdownText

@Composable
internal fun WorkoutInsightMarkdown(
    markdown: String,
    modifier: Modifier = Modifier,
) {
    val insightTextStyle = MaterialTheme.typography.bodySmall.merge(
        TextStyle(
            color = MaterialTheme.colorScheme.onSurface,
            lineHeight = MaterialTheme.typography.bodyMedium.lineHeight,
        )
    )

    MarkdownText(
        markdown = sanitizeInsightMarkdown(markdown),
        modifier = modifier,
        isTextSelectable = true,
        style = insightTextStyle,
        linkColor = MaterialTheme.colorScheme.primary,
        enableSoftBreakAddsNewLine = true,
    )
}

internal fun sanitizeInsightMarkdown(
    markdown: String,
): String {
    val normalizedMarkdown = markdown
        .replace("\r\n", "\n")
        .replace('\r', '\n')
        .replace(Regex("(?im)^\\s*workout_raw_response_(?:start|end)\\s*$"), "")
        .replace("workout_raw_response_start", "")
        .replace("workout_raw_response_end", "")
        .replace(Regex("(?<!\\n)(##\\s+)"), "\n\n$1")
        .replace(Regex("(?<!\\n)(###\\s+)"), "\n\n$1")
        .replace(Regex("(##\\s+[^\\n#-][^\\n#]*?)\\s*(?:-\\s*)+(?=[A-Z0-9'])"), "$1\n- ")
        .replace(Regex("(###\\s+[^\\n#-][^\\n#]*?)\\s*(?:-\\s*)+(?=[A-Z0-9'])"), "$1\n- ")
        .replace(Regex("(##\\s+[^\\n#*-][^\\n#]*?)-\\s+"), "$1\n- ")
        .replace(Regex("([.!?])\\s*-\\s+(?=[A-Z0-9])"), "$1\n- ")
        .replace(Regex("([.!?])\\s*(?:-\\s*){2,}(?=[A-Z0-9'])"), "$1\n- ")
        .replace(Regex("(?m)^-\\s+-\\s+"), "- ")
        .replace(Regex("(?m)^\\s*-\\s+-\\s+"), "- ")
        .replace(Regex("(?<=\\S)\\*(?=\\s*[A-Z0-9])"), "\n- ")
        .replace(Regex("(?<!\\n)(\\*\\S)"), "\n$1")
        .replace(Regex("(?<=\\D)(\\d+)%"), "$1%")
        .replace(Regex("(?<=[A-Za-z])(?=\\d)"), " ")
        .replace(Regex("(?<=\\d)(?=[A-Za-z])"), " ")
        .replace(Regex("[ \t]+"), " ")

    val normalizedLines = normalizedMarkdown
        .lines()
        .mapNotNull { rawLine ->
            val trimmedEnd = rawLine.trimEnd()
            val trimmed = trimmedEnd.trim()
            when {
                trimmed.isEmpty() -> ""
                trimmed == "*" || trimmed == "#" || trimmed == "##" || trimmed == "***" -> null
                trimmed.startsWith("##") -> "## ${trimmed.removePrefix("#").removePrefix("#").trimStart('#', ' ')}".trim()
                trimmed.startsWith("-") || trimmed.startsWith("*") ->
                    "- ${trimmed.removePrefix("-").removePrefix("*").trim()}"
                else -> trimmedEnd
            }
        }

    val builder = StringBuilder()
    var previousWasBlank = true
    for (line in normalizedLines) {
        val isBlank = line.isBlank()
        if (isBlank) {
            if (!previousWasBlank) {
                builder.append("\n\n")
            }
            previousWasBlank = true
            continue
        }

        if (line.startsWith("## ")) {
            if (builder.isNotEmpty() && !builder.endsWith("\n\n")) {
                builder.append("\n\n")
            }
            builder.append(line)
            builder.append("\n\n")
            previousWasBlank = false
            continue
        }

        if (line.startsWith("- ")) {
            if (builder.isNotEmpty() && !builder.endsWith("\n") && !builder.endsWith("\n\n")) {
                builder.append('\n')
            }
            builder.append(line)
            builder.append('\n')
            previousWasBlank = false
            continue
        }

        if (builder.isNotEmpty() && !builder.endsWith("\n") && !builder.endsWith("\n\n")) {
            builder.append('\n')
        }
        builder.append(line)
        builder.append('\n')
        previousWasBlank = false
    }

    return builder.toString()
        .replace(Regex("\n{3,}"), "\n\n")
        .trim()
}

internal fun postProcessInsightMarkdown(
    markdown: String,
    toolContext: WorkoutInsightsToolContext?,
): String {
    val sanitized = sanitizeInsightMarkdown(markdown)
    val workoutSessionContext = toolContext as? WorkoutInsightsToolContext.WorkoutSession ?: return sanitized
    if (!isLiftingDominantLowIntensitySession(workoutSessionContext.markdown)) {
        return sanitized
    }
    return removeLowIntensityLiftingRiskBullets(sanitized)
}

private fun isLiftingDominantLowIntensitySession(
    markdown: String,
): Boolean {
    val weightExerciseCount = Regex("""(?im)\bType[: ]+(WEIGHT|BODY_WEIGHT)\b""")
        .findAll(markdown)
        .count()
    if (weightExerciseCount == 0) return false

    val avgPercentMaxHr = Regex("""Avg % max HR:\s*(\d{1,3})%""", RegexOption.IGNORE_CASE)
        .find(markdown)
        ?.groupValues
        ?.getOrNull(1)
        ?.toIntOrNull()
    val highIntensityExposurePercent = Regex(
        """High-intensity exposure:\s*(\d{1,3})%""",
        RegexOption.IGNORE_CASE
    ).find(markdown)
        ?.groupValues
        ?.getOrNull(1)
        ?.toIntOrNull()

    return highIntensityExposurePercent == 0 && (avgPercentMaxHr ?: Int.MAX_VALUE) <= 60
}

private fun removeLowIntensityLiftingRiskBullets(
    markdown: String,
): String {
    val lines = markdown.lines()
    val builder = StringBuilder()
    var currentSection: String? = null

    lines.forEach { line ->
        when {
            line.startsWith("## ") -> {
                currentSection = line.removePrefix("## ").trim()
                builder.append(line).append('\n')
            }
            currentSection == "Risks" &&
                line.startsWith("- ") &&
                isLowIntensityLiftingRiskBullet(line) -> Unit
            else -> builder.append(line).append('\n')
        }
    }

    return sanitizeInsightMarkdown(builder.toString())
}

private fun isLowIntensityLiftingRiskBullet(
    line: String,
): Boolean {
    val normalized = line.lowercase()
    return normalized.contains("high-intensity exposure") ||
        normalized.contains("high intensity exposure") ||
        normalized.contains("high-intensity territory") ||
        normalized.contains("higher heart rate") ||
        normalized.contains("higher intensity") ||
        normalized.contains("session intensity was not pushed") ||
        normalized.contains("session intensity was not pushed to") ||
        normalized.contains("did not push into high-intensity") ||
        normalized.contains("moderate effort level, which may limit the stimulus")
}
