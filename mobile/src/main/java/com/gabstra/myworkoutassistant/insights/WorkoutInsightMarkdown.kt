package com.gabstra.myworkoutassistant.insights

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.LineHeightStyle
import dev.jeziellago.compose.markdowntext.MarkdownText

@Composable
internal fun WorkoutInsightMarkdown(
    markdown: String,
    modifier: Modifier = Modifier,
    /** When set (e.g. history chat), matches this style instead of the smaller insight-dialog default. */
    baseTypographyStyle: TextStyle? = null,
) {
    val scheme = MaterialTheme.colorScheme
    val base = baseTypographyStyle ?: MaterialTheme.typography.bodySmall
    val insightTextStyle = base.merge(
        TextStyle(
            color = scheme.onSurface,
            lineHeight = base.lineHeight,
            lineHeightStyle = LineHeightStyle(
                alignment = LineHeightStyle.Alignment.Center,
                trim = LineHeightStyle.Trim.None,
            ),
        )
    )

    MarkdownText(
        markdown = compactTopLevelHeadingLevelsForDisplay(sanitizeInsightMarkdown(markdown)),
        modifier = modifier,
        isTextSelectable = true,
        style = insightTextStyle,
        linkColor = scheme.primary,
        enableSoftBreakAddsNewLine = true,
        syntaxHighlightColor = scheme.secondaryContainer,
        syntaxHighlightTextColor = scheme.onSecondaryContainer,
    )
}

/**
 * Markwon scales headings up from body; demoting `##` → `###` keeps hierarchy but reads closer to body text.
 * Only line-start `##` is changed so existing `###`+ sections are untouched.
 */
internal fun compactTopLevelHeadingLevelsForDisplay(markdown: String): String =
    markdown.replace(Regex("""(?m)^##(\s+)"""), "###$1")

/**
 * Normalizes model-produced markdown for [MarkdownText]: line endings, glued prose, star-blob
 * pseudo-headings, section/bullet glue, then line-block layout (see private helpers below).
 */
internal fun sanitizeInsightMarkdown(
    markdown: String,
): String {
    val normalizedMarkdown = markdown
        .replace("\r\n", "\n")
        .replace('\r', '\n')
        // NBSP / figure spaces etc. used as padding (common in LLM output); map to ASCII for width rules.
        .replace(Regex("""[\u00A0\u1680\u2000-\u200A\u202F\u205F\u3000]+"""), " ")
        .let(::insertGluedSentenceAndListBreaks)
        .let(::normalizeStarBlobPseudoHeadings)
        .replace(Regex("(?im)^\\s*workout_raw_response_(?:start|end)\\s*$"), "")
        .replace("workout_raw_response_start", "")
        .replace("workout_raw_response_end", "")
        .replace(Regex("(?<!\\n)(##\\s+)"), "\n\n$1")
        .replace(Regex("(?<!\\n)(###\\s+)"), "\n\n$1")
        .replace(Regex("(##\\s+[^\\n#-][^\\n#]*?)\\s*-\\s+(?=\\*\\*[A-Z0-9])"), "$1\n- ")
        .replace(Regex("(###\\s+[^\\n#-][^\\n#]*?)\\s*-\\s+(?=\\*\\*[A-Z0-9])"), "$1\n- ")
        .replace(Regex("(##\\s+[^\\n#-][^\\n#]*?)\\s*(?:-\\s*)+(?=[A-Z0-9'])"), "$1\n- ")
        .replace(Regex("(###\\s+[^\\n#-][^\\n#]*?)\\s*(?:-\\s*)+(?=[A-Z0-9'])"), "$1\n- ")
        .replace(Regex("(##\\s+[^\\n#*-][^\\n#]*?)-\\s+"), "$1\n- ")
        .replace(Regex("([.!?])\\s*-\\s+(?=[A-Z0-9])"), "$1\n- ")
        .replace(Regex("([.!?])\\s*-\\s+(?=\\*\\*[A-Z0-9])"), "$1\n- ")
        .replace(Regex("([.!?])\\s*(?:-\\s*){2,}(?=[A-Z0-9'])"), "$1\n- ")
        .replace(Regex("(?m)^-\\s+-\\s+"), "- ")
        .replace(Regex("(?m)^\\s*-\\s+-\\s+"), "- ")
        .replace(Regex("(?<=\\S)(?<!\\*)\\*(?!\\*)(?=\\s*[A-Z0-9])"), "\n- ")
        .replace(Regex("(?<![\\n*])(\\*(?!\\*)\\S)"), "\n$1")
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
                else -> trimmed
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

/** Inserts paragraph/list breaks where models glue tokens (`word.Next`, `list:*Item`, `kg).The`, …). */
private fun insertGluedSentenceAndListBreaks(markdown: String): String =
    markdown
        .replace(Regex("""(?<=[a-z])\.(?=[A-Z])"""), ".\n\n")
        .replace(Regex("""(?<=[a-z])!(?=[A-Z])"""), "!\n\n")
        .replace(Regex("""(?<=[a-z])\?(?=[A-Z])"""), "?\n\n")
        // "…kg).The history…" — punctuation glued after ')' before a new sentence.
        .replace(Regex("""\)\.(?=[A-Z][a-z])"""), ").\n\n")
        // "…sessions.2. Next point…" -> split before glued numbered item.
        .replace(Regex("""(?<=[.!?])(?=\d+\.\s*[A-Za-z])"""), "\n\n")
        // "…kg).The history…" — closing paren before a capitalized sentence.
        .replace(Regex("""(?<=[A-Za-z0-9%])\)(?=[A-Z][a-z])"""), ")\n\n")
        .replace(Regex("""([:;]\s*)(\*(?=[A-Za-z0-9]))"""), "$1\n\n$2")

/**
 * LLMs often emit "star blob" pseudo-headings (`***Squat:**`, `**Bench:**`, …) that CommonMark and
 * compose markdown parsers interpret inconsistently. Normalize to real `##` headings; repeat until
 * stable so back-to-back segments all convert.
 *
 * Intentionally does **not** match `**Title**:` (colon after closing bold) so real bold+colon lines stay intact.
 */
private fun normalizeStarBlobPseudoHeadings(markdown: String): String {
    val tripleLeading = Regex(
        """(?<![*])\*{3,}\s*([^*\n:]+?)\s*:\*{1,3}(?!\*)""",
    )
    val doubleBoldHeading = Regex(
        """(?<![*])\*{2}\s*([A-Za-z\u00C0-\u017F][^*\n:]{0,160}?)\s*:\*{1,2}(?!\*)""",
    )
    var s = markdown
    repeat(16) {
        val next = s
            .replace(tripleLeading, "\n\n## $1\n\n")
            .replace(doubleBoldHeading, "\n\n## $1\n\n")
        if (next == s) return s
        s = next
    }
    return s
}

internal fun postProcessInsightMarkdown(
    markdown: String,
    toolContext: WorkoutInsightsToolContext?,
    evidencePrompt: String? = null,
): String {
    var processed = sanitizeInsightMarkdown(markdown)
    if (toolContext != null) {
        processed = replaceUnsupportedExactMetricMentions(
            markdown = processed,
            evidence = buildMetricAllowListEvidence(
                toolContext = toolContext,
                evidencePrompt = evidencePrompt,
            )
        )
    }

    val workoutSessionContext = toolContext as? WorkoutInsightsToolContext.WorkoutSession ?: return processed
    if (!isLiftingDominantLowIntensitySession(workoutSessionContext.markdown)) {
        return processed
    }
    return removeLowIntensityLiftingRiskBullets(processed)
}

private val exactMetricMentionRegex = Regex(
    """(?<![A-Za-z0-9.])\d+(?:\.\d+)?(?:\s*(?:-|to)\s*\d+(?:\.\d+)?)?\s*(?:k\s*)?(?:kg|bpm|%|reps?|sets?|seconds?|minutes?|mins?|km|mi|m|rir)(?=$|[^A-Za-z0-9])""",
    RegexOption.IGNORE_CASE
)

private val setLikeMetricMentionRegex = Regex(
    """(?<![A-Za-z0-9.])\d+(?:\.\d+)?\s*x\s*\d+(?=$|[^A-Za-z0-9.])""",
    RegexOption.IGNORE_CASE
)

private fun replaceUnsupportedExactMetricMentions(
    markdown: String,
    evidence: String,
): String {
    val allowedExactMentions = exactMetricMentionRegex
        .findAll(evidence)
        .map { match -> match.value.normalizeExactMetricMention() }
        .toSet()
    val allowedSetLikeMentions = setLikeMetricMentionRegex
        .findAll(evidence)
        .map { match -> match.value.normalizeSetLikeMetricMention() }
        .toSet()
    if (allowedExactMentions.isEmpty() && allowedSetLikeMentions.isEmpty()) return markdown

    return exactMetricMentionRegex
        .replace(markdown) { match ->
            if (match.value.normalizeExactMetricMention() in allowedExactMentions) {
                match.value
            } else {
                "the recorded value"
            }
        }.let { exactFiltered ->
            setLikeMetricMentionRegex.replace(exactFiltered) { match ->
                if (match.value.normalizeSetLikeMetricMention() in allowedSetLikeMentions) {
                    match.value
                } else {
                    "the recorded set"
                }
            }
        }
        .replace(Regex("\\s+([,.;:])"), "$1")
}

private fun buildMetricAllowListEvidence(
    toolContext: WorkoutInsightsToolContext,
    evidencePrompt: String?,
): String = buildString {
    evidencePrompt
        ?.evidenceSectionForMetricAllowList()
        ?.takeIf { it.isNotBlank() }
        ?.let { promptEvidence ->
            append(promptEvidence)
            append('\n')
        }
    append(toolContext.markdown)
}

private fun String.evidenceSectionForMetricAllowList(): String {
    val markerIndex = listOf(
        "Workout session:",
        "Exercise history:"
    ).map { marker -> lastIndexOf(marker) }.filter { it >= 0 }.maxOrNull()

    return markerIndex
        ?.let { index -> substring(index) }
        ?: this
}

private fun String.normalizeExactMetricMention(): String {
    return lowercase()
        .replace(Regex("\\s+"), " ")
        .replace(Regex("\\s+(?=%)"), "")
        .replace("k kg", "kkg")
        .trim()
}

private fun String.normalizeSetLikeMetricMention(): String {
    return lowercase()
        .replace(Regex("\\s+"), "")
        .trim()
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
