package com.gabstra.myworkoutassistant.insights

import android.text.util.Linkify
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.LineHeightStyle
import dev.jeziellago.compose.markdowntext.MarkdownText
import kotlin.math.abs

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
        markdown = compactTopLevelHeadingLevelsForDisplay(markdown),
        modifier = modifier,
        isTextSelectable = true,
        style = insightTextStyle,
        linkColor = scheme.primary,
        linkifyMask = Linkify.WEB_URLS or Linkify.EMAIL_ADDRESSES,
        enableSoftBreakAddsNewLine = false,
        syntaxHighlightColor = scheme.secondaryContainer,
        syntaxHighlightTextColor = scheme.onSecondaryContainer,
    )
}

/**
 * Prefix of a streamed markdown response containing only complete (newline-terminated) lines —
 * the part that cannot change shape as more text arrives, so it is safe to render while the
 * generation is still running. The in-flight trailing line stays hidden behind the progress
 * status instead of showing half-written markdown. Returns "" before the first line completes.
 */
internal fun settledMarkdownPrefix(partial: String): String {
    val lastLineEnd = partial.lastIndexOf('\n')
    return if (lastLineEnd < 0) "" else partial.substring(0, lastLineEnd + 1)
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

/**
 * Drops the "Exercise highlights" section when it carries no finding — the model is
 * told to write a nothing-to-say bullet when nothing applies, and a whole section
 * that says nothing is noise for the reader.
 */
internal fun removeEmptyExerciseHighlightsSection(markdown: String): String {
    val sectionRegex = Regex(
        """(?ms)^##\s*Exercise highlights\s*\n(.*?)(?=^##\s|\Z)"""
    )
    val section = sectionRegex.find(markdown) ?: return markdown
    val body = section.groupValues[1]
    val saysNothing = body
        .lineSequence()
        .map(String::trim)
        .filter { it.isNotEmpty() }
        .all { line ->
            val lower = line.removePrefix("- ").lowercase()
            lower.startsWith("no ") && (
                lower.contains("highlight") ||
                    lower.contains("exercise-specific") ||
                    lower.contains("exercise level") ||
                    lower.contains("detail") ||
                    lower.contains("nothing")
                )
        }
    if (!saysNothing) return markdown
    return markdown.replaceRange(section.range, "")
        .replace(Regex("""\n{3,}"""), "\n\n")
        .trim() + "\n"
}

internal data class MisquotedLineDrop(
    /** Heading of the `##` section the line belonged to ("What stood out", …); null when none. */
    val sectionHeading: String?,
    /** The dropped line as it appeared (including its "- " bullet prefix). */
    val originalLine: String,
    /** Drop reason: the misquoted text plus the fact-based correction, model-readable. */
    val reason: String,
)

internal data class PostProcessOutcome(
    val markdown: String,
    /** Lines dropped for misquoting facts; candidates for the one-shot rewrite recovery. */
    val misquotedDrops: List<MisquotedLineDrop>,
)

internal fun postProcessInsightMarkdown(
    markdown: String,
    toolContext: WorkoutInsightsToolContext?,
    evidencePrompt: String? = null,
    applySessionTargetSection: Boolean = false,
    enforceNumericContract: Boolean = false,
    preserveMarkdown: Boolean = false,
): String = postProcessInsightMarkdownWithDropReport(
    markdown = markdown,
    toolContext = toolContext,
    evidencePrompt = evidencePrompt,
    applySessionTargetSection = applySessionTargetSection,
    enforceNumericContract = enforceNumericContract,
    preserveMarkdown = preserveMarkdown,
).markdown

internal fun postProcessInsightMarkdownWithDropReport(
    markdown: String,
    toolContext: WorkoutInsightsToolContext?,
    evidencePrompt: String? = null,
    applySessionTargetSection: Boolean = false,
    enforceNumericContract: Boolean = false,
    preserveMarkdown: Boolean = false,
): PostProcessOutcome {
    var processed = if (preserveMarkdown) {
        markdown.replace("\r\n", "\n").replace('\r', '\n').trim()
    } else {
        removeEmptyExerciseHighlightsSection(sanitizeInsightMarkdown(markdown))
    }
    val sessionContext = toolContext as? WorkoutInsightsToolContext.WorkoutSession
    var misquotedDrops: List<MisquotedLineDrop> = emptyList()
    if (toolContext != null) {
        processed = replaceUnsupportedExactMetricMentions(
            markdown = processed,
            evidence = buildMetricAllowListEvidence(
                toolContext = toolContext,
                evidencePrompt = evidencePrompt,
            )
        )
        if (enforceNumericContract) {
            parseSessionNumericFacts(toolContext.markdown)?.let { facts ->
                val (kept, drops) = dropMisquotedLines(processed, facts)
                processed = kept
                misquotedDrops = drops
            }
        }
        processed = removeEmptyMarkdownSections(processed)
    }
    if (applySessionTargetSection && sessionContext?.nextSessionTargetBullet != null) {
        processed = ensureNextSessionTargetSection(processed, sessionContext.nextSessionTargetBullet)
    }

    if (preserveMarkdown) return PostProcessOutcome(processed, misquotedDrops)
    val workoutSessionContext = sessionContext ?: return PostProcessOutcome(processed, misquotedDrops)
    if (!isLiftingDominantLowIntensitySession(workoutSessionContext.markdown)) {
        return PostProcessOutcome(processed, misquotedDrops)
    }
    return PostProcessOutcome(removeLowIntensityLiftingRiskBullets(processed), misquotedDrops)
}

/**
 * Drops lines whose metric mentions disagree with the app-computed facts (right value, wrong
 * meaning — the class the exact-string allowlist cannot catch) and reports them so the
 * generation flow can offer the model one rewrite chance. Read-only w.r.t. surviving text.
 */
private fun dropMisquotedLines(
    markdown: String,
    facts: SessionNumericFacts,
): Pair<String, List<MisquotedLineDrop>> {
    val dropped = mutableListOf<MisquotedLineDrop>()
    val kept = mutableListOf<String>()
    var currentHeading: String? = null
    for (line in markdown.lines()) {
        if (line.startsWith("## ")) {
            currentHeading = line.removePrefix("## ").trim()
        }
        val violations = if (line.isBlank()) emptyList() else validateSessionNumericContract(line, facts)
        if (violations.isEmpty()) {
            kept.add(line)
        } else {
            dropped += MisquotedLineDrop(
                sectionHeading = currentHeading,
                originalLine = line,
                reason = violations.joinToString("; ") { "\"${it.quotedText}\" — ${it.correction}" },
            )
        }
    }
    return kept.joinToString("\n") to dropped
}

/**
 * Re-inserts rewrite-recovered bullets: at the end of their original section when it still
 * exists, otherwise the section heading is re-created (it may have been removed when the drop
 * emptied it). The result is re-sanitized for layout.
 */
internal fun spliceRewrittenBullets(
    markdown: String,
    rewrites: List<Pair<MisquotedLineDrop, String>>,
): String {
    val lines = markdown.lines().toMutableList()
    for ((drop, bullet) in rewrites) {
        val replacement = "- ${bullet.trim().removePrefix("-").trim()}"
        val headingLine = drop.sectionHeading?.let { "## $it" }
        val headingIndex = headingLine?.let { heading ->
            lines.indexOfFirst { it.trim() == heading }
        }?.takeIf { it >= 0 }
        when {
            headingIndex == null && drop.sectionHeading == null -> lines.add(replacement)
            headingIndex == null -> {
                lines.add("")
                lines.add("## ${drop.sectionHeading}")
                lines.add(replacement)
            }
            else -> {
                var insertAt = lines.size
                for (index in headingIndex + 1 until lines.size) {
                    if (lines[index].startsWith("## ")) {
                        insertAt = index
                        break
                    }
                }
                while (insertAt > headingIndex + 1 && lines[insertAt - 1].isBlank()) insertAt--
                lines.add(insertAt, replacement)
            }
        }
    }
    return sanitizeInsightMarkdown(lines.joinToString("\n"))
}

/**
 * A rewrite candidate survives only if it no longer misquotes any fact and every number it
 * mentions is allowlisted by the evidence.
 */
internal fun validateRewrittenLines(
    candidates: List<String>,
    facts: SessionNumericFacts,
    evidence: String,
): List<String> = candidates.filter { candidate ->
    validateSessionNumericContract(candidate, facts).isEmpty() && isAllowlistedLine(candidate, evidence)
}

private fun isAllowlistedLine(line: String, evidence: String): Boolean {
    val filtered = replaceUnsupportedExactMetricMentions(markdown = line, evidence = evidence)
    // A line whose only metrics were unsupported is dropped outright by the allowlist —
    // empty output means the candidate did not survive, not that it was clean.
    if (filtered.isBlank()) return false
    return !filtered.contains(REDACTED_METRIC_VALUE_PHRASE) && !filtered.contains(REDACTED_METRIC_SET_PHRASE)
}

private val nextSessionTargetSectionRegex = Regex(
    """^##\s*next session target[^\n]*\n(.*?)(?=^##\s|\Z)""",
    setOf(RegexOption.IGNORE_CASE, RegexOption.MULTILINE, RegexOption.DOT_MATCHES_ALL),
)

/**
 * Renders the app-composed next-session-target bullet as the whole section body: replaces the
 * model's section when present, appends the section when the model omitted it.
 */
internal fun composeNextSessionTargetSection(markdown: String, bullet: String): String {
    val replacement = "## Next session target\n- ${bullet.trim()}\n"
    val section = nextSessionTargetSectionRegex.find(markdown) ?: return markdown.trimEnd() +
        "\n\n" + replacement
    return markdown.replaceRange(section.range, replacement)
        .replace(Regex("\n{3,}"), "\n\n")
        .trim() + "\n"
}

internal fun ensureNextSessionTargetSection(markdown: String, fallbackBullet: String): String =
    if (nextSessionTargetSectionRegex.find(markdown) == null) {
        composeNextSessionTargetSection(markdown, fallbackBullet)
    } else {
        markdown
    }

/**
 * Removes `##` section headings whose body holds no content at all. Redaction drops can
 * empty a section (e.g. the only "Exercise highlights" bullet carried unsupported numbers),
 * and a bare heading is presentation noise for the reader.
 */
internal fun removeEmptyMarkdownSections(markdown: String): String {
    val lines = markdown.lines()
    val builder = StringBuilder()
    var index = 0
    while (index < lines.size) {
        val line = lines[index]
        if (line.startsWith("## ")) {
            var sectionEnd = index + 1
            while (sectionEnd < lines.size && !lines[sectionEnd].startsWith("## ")) {
                sectionEnd++
            }
            val bodyHasContent = lines.subList(index + 1, sectionEnd).any(String::isNotBlank)
            if (bodyHasContent) {
                lines.subList(index, sectionEnd).forEach { builder.append(it).append('\n') }
            }
            index = sectionEnd
        } else {
            builder.append(line).append('\n')
            index++
        }
    }
    return builder.toString().replace(Regex("\n{3,}"), "\n\n").trim()
}

private val exactMetricMentionRegex = Regex(
    """(?<![A-Za-z0-9.])\d+(?:\.\d+)?(?:\s*(?:[-–—]|to)\s*\d+(?:\.\d+)?)?\s*(?:k\s*)?(?:kg|bpm|%|reps?|sets?|seconds?|minutes?|mins?|km|mi|m|rir)(?=$|[^A-Za-z0-9])""",
    RegexOption.IGNORE_CASE
)

private val setLikeMetricMentionRegex = Regex(
    """(?<![A-Za-z0-9.])\d+(?:\.\d+)?\s*x\s*\d+(?=$|[^A-Za-z0-9.])""",
    RegexOption.IGNORE_CASE
)

private const val REDACTED_METRIC_VALUE_PHRASE = "the recorded value"
private const val REDACTED_METRIC_SET_PHRASE = "the recorded set"

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
    val evidenceDurationsSeconds = extractEvidenceDurationsSeconds(evidence)
    val evidenceDistancesMeters = extractEvidenceDistancesMeters(evidence)
    if (allowedExactMentions.isEmpty() && allowedSetLikeMentions.isEmpty() &&
        evidenceDurationsSeconds.isEmpty() && evidenceDistancesMeters.isEmpty()
    ) return markdown

    fun isSupportedMetric(match: MatchResult): Boolean {
        if (match.value.normalizeExactMetricMention() in allowedExactMentions) return true
        return isSupportedTimeOrDistanceMention(
            mention = match.value,
            evidenceDurationsSeconds = evidenceDurationsSeconds,
            evidenceDistancesMeters = evidenceDistancesMeters,
        )
    }

    val replaced = exactMetricMentionRegex
        .replace(markdown) { match ->
            if (isSupportedMetric(match)) {
                match.value
            } else {
                REDACTED_METRIC_VALUE_PHRASE
            }
        }.let { exactFiltered ->
            setLikeMetricMentionRegex.replace(exactFiltered) { match ->
                if (match.value.normalizeSetLikeMetricMention() in allowedSetLikeMentions) {
                    match.value
                } else {
                    REDACTED_METRIC_SET_PHRASE
                }
            }
        }
        .replace(Regex("\\s+([,.;:])"), "$1")

    // A line whose every metric mention was redacted carries no verifiable content and reads
    // as broken prose ("of the recorded value and the recorded value") — drop the whole line.
    return replaced.lines()
        .filter { line ->
            val hasRedaction = line.contains(REDACTED_METRIC_VALUE_PHRASE) ||
                line.contains(REDACTED_METRIC_SET_PHRASE)
            if (!hasRedaction) return@filter true
            exactMetricMentionRegex.findAll(line).any(::isSupportedMetric) ||
                setLikeMetricMentionRegex.findAll(line).any { match ->
                    match.value.normalizeSetLikeMetricMention() in allowedSetLikeMentions
                }
        }
        .joinToString("\n")
}

private val clockDurationRegex = Regex("""(?<!\d)(\d{1,3}):(\d{2})(?::(\d{2}))?(?!\d)""")
private val timeUnitMentionRegex = Regex("""(\d+(?:\.\d+)?)\s*(seconds?|mins?|minutes?)\b""", RegexOption.IGNORE_CASE)
private val distanceValueUnitRegex = Regex("""(\d+(?:\.\d+)?)\s*(km|mi|m)\b""", RegexOption.IGNORE_CASE)

/**
 * Clock-formatted durations in evidence lines ("Duration: 52:30") carry no unit
 * suffix, so the suffix-based allow-list never sees them; without this scan a
 * model writing "52 minutes and 30 seconds" loses both numbers. Only lines that
 * mention duration are scanned to keep timestamped history rows out.
 */
private fun extractEvidenceDurationsSeconds(evidence: String): List<Double> =
    evidence.lineSequence()
        .filter { it.contains("duration", ignoreCase = true) }
        .flatMap { line -> clockDurationRegex.findAll(line) }
        .filter { m ->
            m.groupValues[2].toInt() < 60 &&
                (m.groupValues[3].isEmpty() || m.groupValues[3].toInt() < 60)
        }
        .map { m ->
            val first = m.groupValues[1].toInt()
            val second = m.groupValues[2].toInt()
            val third = m.groupValues[3]
            if (third.isEmpty()) first * 60.0 + second
            else first * 3600.0 + second * 60.0 + third.toInt()
        }
        .filter { it > 0.0 }
        .plus(
            exactMetricMentionRegex.findAll(evidence)
                .map { it.value }
                .mapNotNull { timeUnitMentionRegex.find(it.lowercase()) }
                .map { m ->
                    val value = m.groupValues[1].toDouble()
                    if (m.groupValues[2].startsWith("s")) value else value * 60.0
                },
        )
        .toList()

private fun extractEvidenceDistancesMeters(evidence: String): List<Double> =
    exactMetricMentionRegex.findAll(evidence)
        .map { it.value }
        .mapNotNull { distanceValueUnitRegex.find(it.lowercase()) }
        .map { m ->
            when (m.groupValues[2]) {
                "km" -> m.groupValues[1].toDouble() * 1000.0
                "mi" -> m.groupValues[1].toDouble() * 1609.344
                else -> m.groupValues[1].toDouble()
            }
        }
        .filter { it > 0.0 }
        .toList()

/**
 * Numeric fallback for the exact-string allow-list: a spelled-out duration
 * ("52 minutes and 30 seconds") survives when it is consistent with an
 * evidence duration, and distances survive across km/m/mi conversions.
 */
private fun isSupportedTimeOrDistanceMention(
    mention: String,
    evidenceDurationsSeconds: List<Double>,
    evidenceDistancesMeters: List<Double>,
): Boolean {
    val normalized = mention.lowercase()
    timeUnitMentionRegex.find(normalized)?.let { m ->
        val value = m.groupValues[1].toDouble()
        val seconds = if (m.groupValues[2].startsWith("s")) value else value * 60.0
        return evidenceDurationsSeconds.any { total ->
            abs(seconds - total) <= 60.0 || abs(seconds - (total % 60.0)) <= 1.0
        }
    }
    distanceValueUnitRegex.find(normalized)?.let { m ->
        val value = m.groupValues[1].toDouble()
        val meters = when (m.groupValues[2]) {
            "km" -> value * 1000.0
            "mi" -> value * 1609.344
            else -> value
        }
        return evidenceDistancesMeters.any { distance ->
            distance > 0.0 && abs(meters - distance) / distance <= 0.02
        }
    }
    return false
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
    if (toolContext is WorkoutInsightsToolContext.WorkoutSession) {
        append('\n')
        append(toolContext.historySessionSummaries.joinToString("\n"))
        append('\n')
        append(toolContext.retrievedHistorySessionDetails.values.joinToString("\n"))
    }
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
        .replace(Regex("[–—]"), "-")
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
