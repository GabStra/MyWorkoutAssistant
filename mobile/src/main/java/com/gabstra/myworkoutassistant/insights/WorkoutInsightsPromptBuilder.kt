package com.gabstra.myworkoutassistant.insights

import com.gabstra.myworkoutassistant.WorkoutTypes
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgressionDao
import com.gabstra.myworkoutassistant.shared.RestHistoryDao
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.export.ExerciseHistoryMarkdownResult
import com.gabstra.myworkoutassistant.shared.export.WorkoutSessionMarkdownResult
import com.gabstra.myworkoutassistant.shared.export.buildExerciseHistoryMarkdown
import com.gabstra.myworkoutassistant.shared.export.buildWorkoutSessionMarkdown
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.util.UUID
import kotlin.math.abs
import kotlin.math.roundToInt

private const val MIN_EXERCISE_SESSIONS = 2
private const val MODEL_CONTEXT_WINDOW_TOKENS = 4_096
private const val RESERVED_OUTPUT_TOKENS = 512
private const val RESERVED_SAFETY_TOKENS = 128
private const val MAX_INPUT_TOKEN_BUDGET =
    MODEL_CONTEXT_WINDOW_TOKENS - RESERVED_OUTPUT_TOKENS - RESERVED_SAFETY_TOKENS
private const val ESTIMATED_CHARS_PER_TOKEN_NUMERATOR = 3
private const val ESTIMATED_CHARS_PER_TOKEN_DENOMINATOR = 1
private const val TARGET_MARKDOWN_CHAR_BUDGET =
    MAX_INPUT_TOKEN_BUDGET * ESTIMATED_CHARS_PER_TOKEN_NUMERATOR / ESTIMATED_CHARS_PER_TOKEN_DENOMINATOR
private const val MIN_MARKDOWN_CHAR_BUDGET = 1_800
private const val MARKDOWN_BUDGET_REDUCTION_STEP = 300
private const val MAX_SECTION_CHAR_BUDGET = 2_400
private const val MAX_SUBSECTION_CHAR_BUDGET = 500
private const val MAX_SESSION_HR_LINES = 6

internal const val WORKOUT_INSIGHTS_SYSTEM_PROMPT = """
You are an on-device workout insights assistant.
Use only the supplied workout history.
Do not invent data.
Do not provide medical advice or diagnose injuries.
If an image is attached, it is the workout session heart-rate chart.
Use the chart to understand shape, peaks, drift, and recovery timing.
Do not describe visual details that are not clearly supported by the chart.
If the chart conflicts with explicit text metrics, prefer the explicit text metrics.
If the history is sparse, trimmed, or inconsistent, say so plainly.
If metrics conflict, prefer the most explicit numeric fields first:
1. explicit Exec, Prev, Best, volume, duration, and executed-set values
2. status labels such as Vs prev, Vs exp, Vs baseline, and State
3. HR cues
If a status label conflicts with explicit numeric values, trust the numeric values and treat the label as inconsistent noise.
Never describe a metric as improved if the numeric value is lower than the previous value.
Base intensity claims on the supplied HR cues, especially Avg % max HR, Peak % max HR, High-intensity exposure, work HR, rest HR, and recovery gap.
Prefer qualitative HR wording over repeating exact session percentages unless the exact figure materially changes the interpretation.
If you quote a session percentage, copy it exactly from the supplied HR line and do not add digits or extra precision.
Do not call a session high-intensity if High-intensity exposure is low and Avg % max HR is modest.
Treat best-to-date or progression signals as performance context, not proof of high fatigue or high intensity by themselves.
If evidence is mixed, prefer a cautious interpretation.
For strength workouts, do not prescribe higher heart rate as the main goal; prioritize load, reps, execution quality, and recovery instead.
Use HR mainly to describe overall effort, density, and recovery, not as the primary target for barbell progression.
Do not turn a low-intensity lifting session into a problem unless the performance data also suggests under-stimulation or drift from plan.
For lifting-dominant sessions, do not recommend higher intensity, higher heart rate, or more overall workload just because session HR was modest.
For interval or conditioning workouts, do not call recovery inadequate just because interval or active-rest heart rate stayed elevated; only say recovery was limited when repeatability, target-zone adherence, or explicit recovery metrics support it.
If a conditioning session is similar to previous, best to date, or stable, do not recommend reducing interval duration or intensity unless the supplied metrics also show missed targets, clear drop-off, or worse repeatability.
Avoid generic advice that could apply to any workout; anchor each point to the most relevant exercises or session signals.
In Risks, only mention a meaningful downside or constraint, not a neutral restatement of the data.
If one exercise improved and another regressed or lagged versus previous, say that explicitly.
Do not ignore later exercises or treat any lift as inherently less important unless the supplied data makes that clear.
Use session-level HR summary and zone-time distribution only to describe effort distribution and density.
Do not restate chart variability as a risk unless the explicit workout metrics also show a meaningful problem.
If the clearest limiter is one lagging exercise, use that in Risks instead of generic heart-rate wording.
Respond in markdown with exactly these sections:
## Summary
## Signals
## Risks
## Next session
Keep the response terse, practical, and specific.
Limit each section to at most 2 short bullets.
Keep each bullet to one sentence when possible.
Start each bullet with `- `.
Put each heading and each bullet on its own line.
Do not add any introduction or conclusion outside the required sections.
Before finalizing, silently verify:
- the markdown structure is valid
- every claim matches the supplied numbers
- no bullet says a value increased if the number decreased
- mixed outcomes across exercises are stated explicitly when present
"""

internal const val EXERCISE_INSIGHTS_SYSTEM_PROMPT = """
You are an on-device exercise insights assistant.
Use only the supplied exercise history.
Do not invent data.
Do not provide medical advice or diagnose injuries.
If the history is sparse, trimmed, or inconsistent, say so plainly.
Focus on the latest completed session first, then use the recent sessions as trend context.
Prefer the most direct progression fields first:
1. Progression state, Vs expected, Vs previous baseline
2. explicit expected vs executed set summaries and volume
3. HR cues
Never describe a metric as improved if the numeric value is lower than the comparison value.
If the latest session met plan but still lagged the previous baseline or recent trend, say that explicitly.
Use HR mainly as supporting context for effort and recovery, not as the main target for strength progression.
Avoid generic advice; anchor every point to the latest session or the recent trend.
Respond in markdown with exactly these sections:
## Summary
## Signals
## Risks
## Next session
Keep the response terse, practical, and specific.
Limit each section to at most 2 short bullets.
Keep each bullet to one sentence when possible.
Start each bullet with `- `.
Put each heading and each bullet on its own line.
Do not add any introduction or conclusion outside the required sections.
Before finalizing, silently verify:
- the markdown structure is valid
- every claim matches the supplied numbers
- no bullet says a value increased if the number decreased
- mixed signals across latest session, baseline, and trend are stated explicitly when present
"""

sealed class WorkoutInsightsPromptResult {
    data class Success(
        val title: String,
        val prompt: String,
        val systemPrompt: String,
    ) : WorkoutInsightsPromptResult()

    data class Failure(val message: String) : WorkoutInsightsPromptResult()
}

private data class CompactWorkoutSectionData(
    val heading: String,
    val subsections: List<CompactWorkoutSubsectionData>,
)

private data class CompactWorkoutSubsectionData(
    val title: String,
    val lines: List<String>,
)

private val WORKOUT_SESSION_ALLOWED_SUBSECTIONS = linkedSetOf(
    "Context",
    "Planned",
    "Athlete Context",
    "Session Heart Rate",
    "Executed",
    "Previous Session",
    "Best To Date",
    "Recovery Context",
    "Coaching Signals",
)

suspend fun buildExerciseInsightsPrompt(
    exercise: Exercise,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    restHistoryDao: RestHistoryDao,
    exerciseSessionProgressionDao: ExerciseSessionProgressionDao,
    workouts: List<Workout>,
    workoutStore: WorkoutStore,
): WorkoutInsightsPromptResult {
    return when (
        val markdownResult = buildExerciseHistoryMarkdown(
            exercise = exercise,
            workoutHistoryDao = workoutHistoryDao,
            setHistoryDao = setHistoryDao,
            restHistoryDao = restHistoryDao,
            exerciseSessionProgressionDao = exerciseSessionProgressionDao,
            workouts = workouts,
            workoutStore = workoutStore
        )
    ) {
        is ExerciseHistoryMarkdownResult.Failure -> WorkoutInsightsPromptResult.Failure(markdownResult.message)
        is ExerciseHistoryMarkdownResult.Success -> {
            WorkoutInsightsPromptResult.Success(
                title = "${exercise.name} insights",
                prompt = buildExercisePrompt(markdownResult.markdown),
                systemPrompt = EXERCISE_INSIGHTS_SYSTEM_PROMPT
            )
        }
    }
}

suspend fun buildWorkoutSessionInsightsPrompt(
    workoutHistoryId: UUID,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    restHistoryDao: RestHistoryDao,
    exerciseSessionProgressionDao: ExerciseSessionProgressionDao,
    workoutStore: WorkoutStore,
): WorkoutInsightsPromptResult {
    return when (
        val markdownResult = buildWorkoutSessionMarkdown(
            workoutHistoryId = workoutHistoryId,
            workoutHistoryDao = workoutHistoryDao,
            setHistoryDao = setHistoryDao,
            restHistoryDao = restHistoryDao,
            exerciseSessionProgressionDao = exerciseSessionProgressionDao,
            workoutStore = workoutStore
        )
    ) {
        is WorkoutSessionMarkdownResult.Failure -> WorkoutInsightsPromptResult.Failure(markdownResult.message)
        is WorkoutSessionMarkdownResult.Success -> {
            val workoutType = workoutHistoryDao.getWorkoutHistoryById(workoutHistoryId)
                ?.let { history -> workoutStore.workouts.find { it.id == history.workoutId } }
                ?.type
            val workoutCategoryLine = workoutType
                ?.let(::buildWorkoutCategoryContextLine)
                ?.let { "$it\n" }
                .orEmpty()
            val workoutCategoryGuidance = workoutType
                ?.let(::buildWorkoutCategoryPromptGuidance)
                ?.let { "$it\n" }
                .orEmpty()

            WorkoutInsightsPromptResult.Success(
                title = "Workout session insights",
                prompt = buildWorkoutSessionPrompt(
                    markdown = markdownResult.markdown,
                    workoutCategoryGuidance = workoutCategoryGuidance,
                    workoutCategoryLine = workoutCategoryLine
                ),
                systemPrompt = WORKOUT_INSIGHTS_SYSTEM_PROMPT
            )
        }
    }
}

internal fun buildExercisePrompt(
    markdown: String,
): String = buildPromptWithinBudget(EXERCISE_INSIGHTS_SYSTEM_PROMPT) { charBudget ->
    val compactedMarkdown = compactExerciseHistoryMarkdown(
        markdown = markdown,
        markdownCharBudget = charBudget
    )
    normalizePromptLayout(
        listOf(
            "Analyze this exercise history and provide focused training insights.",
            "Focus on the latest completed session first, then the recent trend.",
            "Compare executed performance against expected work and the previous baseline.",
            "If the latest session met plan but still lagged baseline or recent trend, say that explicitly.",
            "Use HR cues as supporting context only.",
            "Be concise: at most 2 short bullets per required section.",
            "Ground every point in the supplied data.",
            "",
            "Exercise history:",
            compactedMarkdown
        ).joinToString("\n")
    )
}

internal fun buildWorkoutSessionPrompt(
    markdown: String,
    workoutCategoryGuidance: String,
    workoutCategoryLine: String,
): String = buildPromptWithinBudget(WORKOUT_INSIGHTS_SYSTEM_PROMPT) { charBudget ->
    val compactedMarkdown = compactWorkoutSessionMarkdown(
        markdown = markdown,
        markdownCharBudget = charBudget
    )
    val guidanceBlock = listOfNotNull(
        workoutCategoryGuidance.trim().takeIf { it.isNotBlank() },
        buildWorkoutStructurePromptGuidance(
            workoutCategoryLine = workoutCategoryLine,
            markdown = compactedMarkdown
        )
    ).joinToString("\n")
    normalizePromptLayout(
        listOfNotNull(
            "Analyze this completed workout session and provide practical coaching insights.",
            "Focus on what went well, what drifted from plan, likely fatigue/recovery signals, and one clear recommendation for the next session.",
            "Be concise: at most 2 short bullets per required section.",
            "Use HR cues carefully: low High-intensity exposure and modest Avg % max HR usually indicate a low-to-moderate intensity session.",
            "Use session-level zone time to describe intensity distribution when it is provided.",
            "Prefer concise HR wording like modest Avg % max HR or mostly Z0-Z1 over repeating exact decimals unless the exact value matters.",
            "Do not infer high fatigue or high intensity from volume alone.",
            "For lifting sessions, do not recommend chasing a higher Avg % max HR unless the workout is explicitly conditioning-focused.",
            "Compare each exercise against plan, previous, and best-to-date performance.",
            "Do not flatten mixed results into overall progress when the exercises diverged.",
            "For numeric comparisons, read carefully:",
            "- lower current volume than previous = below previous",
            "- equal executed sets to plan = met plan",
            "- best-to-date on one exercise does not imply best-to-date on the whole session",
            "If current top load is higher than previous, mention that explicitly even if current volume is lower.",
            "Use load-profile facts when present: top load and sets at top load can matter even when total volume is lower.",
            "If Exec, Prev, or Best numbers disagree with status labels, trust the numbers.",
            "If most exercises are WEIGHT or BODY_WEIGHT, treat the session as lifting-dominant even if the workout category label is generic.",
            "For lifting-dominant sessions, modest session HR or low high-intensity exposure is descriptive, not a problem by itself.",
            "Do not recommend a higher intensity cue, higher heart rate, or more overall workload unless the lifting performance data shows clear underdosing or drift from plan.",
            "Ground every point in the supplied data.",
            guidanceBlock.takeIf { it.isNotBlank() },
            "",
            "Workout session:",
            "${workoutCategoryLine}$compactedMarkdown"
        ).joinToString("\n")
    )
}

private inline fun buildPromptWithinBudget(
    systemPrompt: String,
    promptBuilder: (markdownCharBudget: Int) -> String,
): String {
    var markdownCharBudget = TARGET_MARKDOWN_CHAR_BUDGET
    var bestPrompt = promptBuilder(markdownCharBudget)

    while (
        estimateTokenCount(systemPrompt) + estimateTokenCount(bestPrompt) >
        MAX_INPUT_TOKEN_BUDGET &&
        markdownCharBudget > MIN_MARKDOWN_CHAR_BUDGET
    ) {
        markdownCharBudget = (markdownCharBudget - MARKDOWN_BUDGET_REDUCTION_STEP)
            .coerceAtLeast(MIN_MARKDOWN_CHAR_BUDGET)
        bestPrompt = promptBuilder(markdownCharBudget)
    }

    return bestPrompt
}

internal fun compactExerciseHistoryMarkdown(
    markdown: String,
    markdownCharBudget: Int = TARGET_MARKDOWN_CHAR_BUDGET,
): String {
    val trimmed = markdown.trim()
    val sessionBlocks = splitMarkdownBlocks(trimmed, Regex("(?m)^## S\\d+:"))
    if (sessionBlocks.size <= 1) return trimmed.takeWithinBudget(markdownCharBudget)

    val header = compactExerciseHeader(sessionBlocks.first())
    val sessions = sessionBlocks.drop(1)
    val maxSessionsToKeep = sessions.size

    for (sessionsToKeep in maxSessionsToKeep downTo MIN_EXERCISE_SESSIONS) {
        val recentSessions = sessions.takeLast(sessionsToKeep).mapNotNull(::compactExerciseSessionBlock)
        val candidate = buildString {
            append(header.trim())
            append("\n\n")
            if (sessionsToKeep < sessions.size) {
                append("_Only the most recent ")
                append(sessionsToKeep)
                append(" sessions are included below to stay within the local model context window._\n\n")
            }
            append(recentSessions.joinToString("\n\n") { it.trim() })
        }.trim()
        if (candidate.length <= markdownCharBudget) {
            return candidate
        }
    }

    val fallbackSessions = sessions
        .takeLast(MIN_EXERCISE_SESSIONS)
        .mapNotNull(::compactExerciseSessionBlock)
        .map { it.takeWithinBudget(MAX_SECTION_CHAR_BUDGET) }
    return buildString {
        append(header.takeWithinBudget(MAX_SECTION_CHAR_BUDGET))
        append("\n\n")
        append("_Only the most recent ")
        append(MIN_EXERCISE_SESSIONS)
        append(" sessions are included below, with older details trimmed to fit the local model context window._\n\n")
        append(fallbackSessions.joinToString("\n\n"))
    }.trim().takeWithinBudget(markdownCharBudget)
}

private fun compactExerciseHeader(
    headerMarkdown: String,
): String {
    val lines = headerMarkdown
        .lines()
        .map { it.trimEnd() }
        .filter { it.isNotBlank() }

    val compacted = lines.filterNot { line ->
        line.contains("| Weights:", ignoreCase = true) ||
            line.startsWith("- Max HR:", ignoreCase = true) ||
            line.startsWith("- Age:", ignoreCase = true)
    }.map { line ->
        if (line.startsWith("# ") && line.contains("| Weights:")) {
            line.substringBefore("| Weights:").trimEnd()
        } else {
            humanizeDenseMetrics(normalizeCompactRangeLine(line))
        }
    }

    return compacted.joinToString("\n")
}

private fun compactExerciseSessionBlock(
    sessionMarkdown: String,
): String? {
    val trimmed = sessionMarkdown.trim()
    if (trimmed.isBlank()) return null

    val parts = splitMarkdownBlocks(trimmed, Regex("(?m)^#### "))
    val headingBlockLines = parts.firstOrNull()
        ?.lineSequence()
        ?.map { it.trim() }
        ?.filter { it.isNotBlank() }
        ?.toList()
        .orEmpty()
    val heading = headingBlockLines.firstOrNull().orEmpty()
    if (heading.isBlank()) return null

    val metadataLines = headingBlockLines.drop(1)
        .filter { line ->
            line.startsWith("- Template position:") ||
                line.startsWith("- Session BW:")
        }
        .take(2)

    val compactedSubsections = parts.drop(1).mapNotNull { subsection ->
        val normalized = subsection.trim()
        val title = normalized.substringBefore('\n').removePrefix("#### ").trim()
        when (title) {
            "Session Heart Rate" -> compactExerciseSessionHeartRateSubsection(normalized)
            "Progression Context" -> compactExerciseProgressionSubsection(normalized)
            "Executed Timeline" -> compactExerciseTimelineSubsection(normalized)
            else -> null
        }
    }

    if (compactedSubsections.isEmpty()) {
        return listOf(heading)
            .plus(metadataLines)
            .joinToString("\n")
            .takeWithinBudget(MAX_SECTION_CHAR_BUDGET)
    }

    return buildString {
        append(compactExerciseSessionHeading(heading))
        append('\n')
        metadataLines.forEach { line ->
            append(compactStructuredMetadataLine(line))
            append('\n')
        }
        compactedSubsections.forEachIndexed { index, subsection ->
            append('\n')
            append(subsection)
            if (index < compactedSubsections.lastIndex) {
                append('\n')
            }
        }
    }.trim().takeWithinBudget(MAX_SECTION_CHAR_BUDGET)
}

private fun compactExerciseSessionHeartRateSubsection(
    subsectionMarkdown: String,
): String? {
    val lines = subsectionMarkdown
        .lineSequence()
        .drop(1)
        .map { it.trim() }
        .filter { it.isNotBlank() }
        .toList()

    val compactedLines = compactSessionHeartRateLines(lines)
        .filter { line ->
            line.startsWith("- Avg % max HR:") ||
                line.startsWith("- Peak % max HR:") ||
                line.startsWith("- High-intensity exposure:")
        }
        .filterNot { line ->
            line == "- High-intensity exposure: 0% of samples"
        }
        .take(3)

    if (compactedLines.isEmpty()) return null
    return renderExerciseSubsection("Session Heart Rate", compactedLines)
}

private fun compactExerciseProgressionSubsection(
    subsectionMarkdown: String,
): String? {
    val lines = subsectionMarkdown
        .lineSequence()
        .drop(1)
        .map { it.trim() }
        .filter { it.isNotBlank() }
        .toList()

    val compactedLines = lines
        .filterNot { line ->
            line.startsWith("- Set Differences:") ||
                line.startsWith("- Note:")
        }
        .map { line ->
            line
                .replace("- State:", "- Progression state:")
                .replace("- Comparison vs expected:", "- Vs expected:")
                .replace("- Comparison vs previous successful baseline:", "- Vs previous baseline:")
        }
        .map(::normalizeMetricLine)
        .map(::compactRepeatedEntryListLine)
        .filter { line ->
            line.startsWith("- Progression state:") ||
                line.startsWith("- Expected:") ||
                line.startsWith("- Executed:") ||
                line.startsWith("- Vs expected:") ||
                line.startsWith("- Vs previous baseline:") ||
                line.startsWith("- Volume:")
        }
        .map(::compactLabelLine)
        .take(6)

    if (compactedLines.isEmpty()) return null
    return renderExerciseSubsection("Progression Context", compactedLines)
}

private fun compactExerciseTimelineSubsection(
    subsectionMarkdown: String,
): String? {
    val lines = subsectionMarkdown
        .lineSequence()
        .drop(1)
        .map { it.trim() }
        .filter { it.isNotBlank() }
        .toList()

    val compactedLines = lines
        .filter { line ->
            line.startsWith("S") || line.startsWith("[skipped] S")
        }
        .map(::normalizeCompactRangeLine)
        .map(::humanizeDenseMetrics)
        .take(2)

    if (compactedLines.isEmpty()) return null
    return renderExerciseSubsection("Executed Timeline", compactedLines)
}

private fun renderExerciseSubsection(
    title: String,
    lines: List<String>,
): String = renderStructuredSubsection(title, lines)

internal fun compactWorkoutSessionMarkdown(
    markdown: String,
    markdownCharBudget: Int = TARGET_MARKDOWN_CHAR_BUDGET,
): String {
    val trimmed = markdown.trim()

    val blocks = splitMarkdownBlocks(trimmed, Regex("(?m)^### "))
    if (blocks.size <= 1) {
        return compactWorkoutTopLevelBlock(trimmed).takeWithinBudget(markdownCharBudget)
    }

    val header = compactWorkoutTopLevelBlock(blocks.first().trim())
    val compactSections = blocks.drop(1).mapNotNull { compactWorkoutSectionData(it) }

    val compacted = buildString {
        append(header)
        append("\n\n")
        append(compactSections.joinToString("\n\n") { renderCompactWorkoutSection(it) })
    }.trim()

    if (compacted.length <= markdownCharBudget) return compacted

    val reducedSections = compactSections.map { renderCompactWorkoutSection(it).takeWithinBudget(MAX_SECTION_CHAR_BUDGET) }
    return buildString {
        append(header.takeWithinBudget(MAX_SECTION_CHAR_BUDGET))
        append("\n\n")
        append(reducedSections.joinToString("\n\n"))
    }.trim().takeWithinBudget(markdownCharBudget)
}

private fun compactWorkoutTopLevelBlock(blockMarkdown: String): String {
    val trimmed = blockMarkdown.trim()
    if (!trimmed.contains("#### ")) {
        return trimmed
    }

    val lines = trimmed.lines()
    val firstSubsectionIndex = lines.indexOfFirst { it.startsWith("#### ") }
    if (firstSubsectionIndex == -1) {
        return trimmed
    }

    val header = lines.take(firstSubsectionIndex)
        .joinToString("\n")
        .trim()
    val subsectionsMarkdown = lines.drop(firstSubsectionIndex)
        .joinToString("\n")
        .trim()
    val subsections = splitMarkdownBlocks(subsectionsMarkdown, Regex("(?m)^#### "))
        .mapNotNull { subsection ->
            val normalized = subsection.trim()
            val title = normalized.substringBefore('\n').removePrefix("#### ").trim()
            if (title !in WORKOUT_SESSION_ALLOWED_SUBSECTIONS) return@mapNotNull null
            compactWorkoutSubsectionData(title, normalized)
        }

    if (subsections.isEmpty()) {
        return header
    }

    return buildString {
        if (header.isNotBlank()) {
            append(header)
            append("\n\n")
        }
        append(subsections.joinToString("\n") { subsection ->
            renderStructuredSubsection(subsection.title, subsection.lines)
        })
    }.trim()
}

private fun compactWorkoutSectionData(sectionMarkdown: String): CompactWorkoutSectionData? {
    val trimmed = sectionMarkdown.trim()
    val parts = splitMarkdownBlocks(trimmed, Regex("(?m)^#### "))
    if (parts.isEmpty()) return null

    val heading = parts.first().trim()
    if (
        heading.equals("### Warm Up", ignoreCase = true) ||
        heading.equals("### Warm-Up", ignoreCase = true) ||
        heading.equals("### Cool Down", ignoreCase = true) ||
        heading.equals("### Cool-Down", ignoreCase = true)
    ) return null
    val keptSubsections = parts.drop(1).mapNotNull { subsection ->
        val normalized = subsection.trim()
        val title = normalized.substringBefore('\n').removePrefix("#### ").trim()
        if (title !in WORKOUT_SESSION_ALLOWED_SUBSECTIONS) return@mapNotNull null
        compactWorkoutSubsectionData(title, normalized)
    }

    if (keptSubsections.isEmpty()) return null

    return normalizeWorkoutSectionComparisonSignals(
        CompactWorkoutSectionData(
        heading = heading,
        subsections = keptSubsections
        )
    )
}

private fun compactWorkoutSubsectionData(
    title: String,
    subsectionMarkdown: String,
): CompactWorkoutSubsectionData? {
    val bodyLines = subsectionMarkdown
        .lineSequence()
        .drop(1)
        .map { it.trim() }
        .filter { it.isNotBlank() }
        .toList()

    val compactedBody = when (title) {
        "Context" -> compactExerciseContextLines(bodyLines)
        "Planned" -> emptyList()
        "Session Heart Rate" -> compactSessionHeartRateLines(bodyLines)
        "Executed" -> compactExecutedLines(bodyLines)
        "Previous Session" -> compactPreviousSessionLines(bodyLines)
        "Best To Date" -> compactBestToDateLines(bodyLines)
        "Recovery Context" -> compactRecoveryContextLines(bodyLines)
        "Coaching Signals" -> compactCoachingSignalLines(bodyLines)
        "Athlete Context" -> compactAthleteContextLines(bodyLines)
        else -> bodyLines
    }

    if (compactedBody.isEmpty()) return null

    return CompactWorkoutSubsectionData(
        title = title,
        lines = compactedBody.takeWhileBudget(MAX_SUBSECTION_CHAR_BUDGET)
    )
}

private fun compactSessionHeartRateLines(lines: List<String>): List<String> {
    val normalizedLines = lines
        .filterNot { line ->
            line.contains("Median:", ignoreCase = true) ||
                line.contains("Std dev:", ignoreCase = true) ||
            line.contains("Standard zones", ignoreCase = true) ||
            line.contains("Stored HR samples", ignoreCase = true) ||
            line.contains("Valid HR samples", ignoreCase = true) ||
            line.contains("Valid HR coverage", ignoreCase = true) ||
            line.contains("Approx. recorded HR span", ignoreCase = true) ||
            line.contains("Workout duration", ignoreCase = true) ||
            line.contains("Time at or above 90%", ignoreCase = true) ||
            line.contains("Max HR reference", ignoreCase = true)
        }
        .map { line ->
            normalizeMetricLine(
                line
                .replace("Min–Max:", "Range:")
                .replace("MinMax:", "Range:")
                .replace("Average as % of max HR:", "Avg % max HR:")
                .replace("Peak as % of max HR:", "Peak % max HR:")
                .replace("Average as % heart-rate reserve:", "Avg % HR reserve:")
                .replace("Peak as % heart-rate reserve:", "Peak % HR reserve:")
                .replace("Time at or above 85% of max HR:", "High-intensity exposure:")
            )
        }
        .map(::humanizeDenseMetrics)
    val zoneTimeLine = buildApproxZoneTimeLine(lines)
    return normalizedLines
        .filter { line ->
            line.startsWith("- Mean:") ||
                line.startsWith("- Range:") ||
                line.startsWith("- Avg % max HR:") ||
                line.startsWith("- Peak % max HR:") ||
                line.startsWith("- High-intensity exposure:")
        }
        .plus(listOfNotNull(zoneTimeLine))
        .map(::simplifySessionHeartRateMetricLine)
        .sortedBy { sessionHeartRateLinePriority(it) }
        .take(MAX_SESSION_HR_LINES)
        .map(::compactLabelLine)
}

private fun simplifySessionHeartRateMetricLine(
    line: String,
): String {
    return line.replace(
        Regex("""(- (?:Avg|Peak) % (?:max HR|HR reserve): )(\d+(?:\.\d+)?)%""")
    ) { match ->
        val roundedPercent = match.groupValues[2].toDoubleOrNull()
            ?.roundToInt()
            ?.toString()
            ?: match.groupValues[2]
        "${match.groupValues[1]}$roundedPercent%"
    }
}

private fun compactSignalLines(lines: List<String>): List<String> {
    return lines
        .filterNot { line ->
            line.equals("- None", ignoreCase = true) ||
            line.startsWith("- Workout:") ||
            line.startsWith("- Date:") ||
            line.startsWith("- Note:") ||
            line.matches(Regex("-\\s*S\\d+:.*")) ||
            line.contains("selected", ignoreCase = true)
        }
        .map(::humanizeDenseMetrics)
        .distinct()
        .take(6)
}

private fun compactExecutedLines(lines: List<String>): List<String> {
    val compacted = compactSignalLines(lines)
        .filter { line ->
            line.startsWith("- Total volume:") ||
                line.startsWith("- Total duration:") ||
                line.startsWith("- Set summary:")
        }
        .map(::stripLikelyWarmupSetSummaryLine)
        .map(::compactRepeatedEntryListLine)
        .map(::compactLabelLine)

    val prioritized = buildList {
        compacted.firstOrNull { it.startsWith("- Sets:") }?.let(::add)
        compacted.firstOrNull { it.startsWith("- Volume:") || it.startsWith("- Duration:") }?.let(::add)
    }

    return if (prioritized.isNotEmpty()) prioritized else compacted.take(2)
}

private fun compactPreviousSessionLines(lines: List<String>): List<String> {
    if (lines.any { it.equals("- None", ignoreCase = true) || it.equals("None", ignoreCase = true) }) {
        return listOf("- No previous session")
    }

    val setsLine = buildHistoricalSessionSetsLine(lines)
    val compacted = compactSignalLines(lines)
        .filter { line ->
            line.startsWith("- Total volume:") ||
                line.startsWith("- Total duration:") ||
                line.startsWith("- Progression state:")
        }
        .map(::compactLabelLine)

    val metricLine = compacted.firstOrNull {
        it.startsWith("- Volume:") || it.startsWith("- Duration:")
    }
    val prioritized = buildList {
        setsLine?.let(::add)
        metricLine?.let(::add)
    }

    return if (prioritized.isNotEmpty()) prioritized else compacted.take(2)
}

private fun buildHistoricalSessionSetsLine(
    lines: List<String>,
): String? {
    val explicitSetSummary = lines.firstOrNull { it.startsWith("- Set summary:") }
        ?.let(::stripLikelyWarmupSetSummaryLine)
        ?.let(::compactRepeatedEntryListLine)
        ?.let(::normalizeMetricLine)
        ?.let(::compactLabelLine)
    if (explicitSetSummary != null) return explicitSetSummary

    val setEntries = lines.mapNotNull(::extractHistoricalSetEntry)
    if (setEntries.isEmpty()) return null
    return compactLabelLine(
        normalizeMetricLine(
            compactRepeatedEntryListLine("- Set summary: ${setEntries.joinToString(", ")}")
        )
    )
}

private fun extractHistoricalSetEntry(
    line: String,
): String? {
    val payload = Regex("""^- S\d+:\s*(.+)$""")
        .find(line.trim())
        ?.groupValues
        ?.getOrNull(1)
        ?.trim()
        ?: return null
    return payload
        .substringBefore(" |")
        .replace('×', 'x')
        .replace(Regex("""\s+"""), " ")
        .trim()
        .takeIf { it.isNotBlank() }
}

private fun compactBestToDateLines(lines: List<String>): List<String> {
    val compacted = compactSignalLines(lines)
        .filter { line ->
            line.startsWith("- Total volume:") ||
                line.startsWith("- Total duration:") ||
                line.startsWith("- Progression state:")
        }
        .map(::compactLabelLine)

    val metricLine = compacted.firstOrNull {
        it.startsWith("- Volume:") || it.startsWith("- Duration:")
    }
    val prioritized = buildList {
        metricLine?.let(::add)
    }

    return if (prioritized.isNotEmpty()) prioritized else compacted.take(2)
}

private fun compactRecoveryContextLines(lines: List<String>): List<String> {
    return compactSignalLines(lines)
        .filter { line ->
            line.startsWith("- Work HR:") ||
                line.startsWith("- Rest HR:") ||
                line.startsWith("- Work samples in target zone:")
        }
        .sortedBy { recoveryLinePriority(it) }
        .take(3)
        .map(::compactLabelLine)
}

private fun compactExerciseContextLines(lines: List<String>): List<String> {
    return lines
        .map(::normalizeMetricLine)
        .filter { line ->
            line.startsWith("- Type:") ||
                line.startsWith("- Equipment:") ||
                line.startsWith("- Rep range:") ||
                line.startsWith("- Load range:") ||
                line.startsWith("- Progression mode:") ||
                line.startsWith("- Exercise target zone:") ||
                line.startsWith("- Intra-set rest:") ||
                line.startsWith("- Warm-up sets:") ||
                line.startsWith("- Notes:")
        }
        .sortedBy { exerciseContextLinePriority(it) }
        .take(5)
        .map(::compactLabelLine)
}

private fun compactPlannedLines(lines: List<String>): List<String> {
    val normalizedEntries = lines
        .map(::humanizeDenseMetrics)
        .filter { line -> line.startsWith("- P") }

    if (normalizedEntries.isEmpty()) {
        return emptyList()
    }

    buildCompactPlannedSummary(normalizedEntries)?.let { compactSummary ->
        return listOf("- Plan: $compactSummary")
    }

    val plannedEntries = normalizedEntries
        .map { line -> compactPlannedEntry(line.removePrefix("- ").trim()) }
    return listOf("- Plan: ${plannedEntries.joinToString("; ")}")
}

private data class PlannedWorkEntry(
    val descriptor: String,
    val reps: Int,
)

private fun buildCompactPlannedSummary(
    lines: List<String>,
): String? {
    val entries = lines.map { it.removePrefix("- ").trim() }
    val workEntries = entries.mapNotNull(::parsePlannedWorkEntry)
    val restSeconds = entries.mapNotNull(::parsePlannedRestSeconds)
    if (workEntries.isEmpty() || workEntries.size + restSeconds.size != entries.size) {
        return null
    }

    val workSummary = when {
        workEntries.map { it.descriptor }.distinct().size == 1 -> {
            val descriptor = workEntries.first().descriptor
            val reps = workEntries.map { it.reps }
            if (reps.distinct().size == 1) {
                "${workEntries.size} sets of $descriptor x ${reps.first()} reps"
            } else {
                "$descriptor for ${reps.joinToString(", ")} reps"
            }
        }
        else -> workEntries.joinToString("; ") { "${it.descriptor} x ${it.reps} reps" }
    }

    val restSummary = if (restSeconds.isEmpty()) {
        ""
    } else {
        val uniqueRestSeconds = restSeconds.distinct()
        if (uniqueRestSeconds.size == 1) {
            " | rest ${uniqueRestSeconds.first()} s"
        } else {
            " | rest ${uniqueRestSeconds.minOrNull()}-${uniqueRestSeconds.maxOrNull()} s"
        }
    }

    return workSummary + restSummary
}

private fun parsePlannedWorkEntry(
    entry: String,
): PlannedWorkEntry? {
    Regex(
        """^P\s*\d+:\s*Body weight \+\s*([0-9.]+)\s*kg\s*x\s*(\d+)\s*reps$""",
        RegexOption.IGNORE_CASE
    ).matchEntire(entry)?.let { match ->
        return PlannedWorkEntry(
            descriptor = "body weight + ${match.groupValues[1]} kg",
            reps = match.groupValues[2].toIntOrNull() ?: return null
        )
    }

    Regex(
        """^P\s*\d+:\s*([0-9.]+)\s*kg\s*x\s*(\d+)\s*reps$""",
        RegexOption.IGNORE_CASE
    ).matchEntire(entry)?.let { match ->
        return PlannedWorkEntry(
            descriptor = "${match.groupValues[1]} kg",
            reps = match.groupValues[2].toIntOrNull() ?: return null
        )
    }

    return null
}

private fun parsePlannedRestSeconds(
    entry: String,
): Int? {
    return Regex(
        """^P\s*\d+:\s*([0-9.]+)\s+seconds rest$""",
        RegexOption.IGNORE_CASE
    ).matchEntire(entry)?.groupValues?.getOrNull(1)?.toIntOrNull()
}

private fun compactPlannedEntry(entry: String): String {
    Regex("""^P\s*(\d+):\s*(.+?)\s+seconds rest$""").matchEntire(entry)?.let { match ->
        return "Step ${match.groupValues[1]}: rest ${match.groupValues[2]} s"
    }
    Regex("""^P\s*(\d+):\s*Body weight \+\s*([0-9.]+)\s*kg\s*x\s*(\d+)\s*reps$""").matchEntire(entry)
        ?.let { match ->
            return "Step ${match.groupValues[1]}: body weight + ${match.groupValues[2]} kg x ${match.groupValues[3]} reps"
        }
    Regex("""^P\s*(\d+):\s*([0-9.]+)\s*kg\s*x\s*(\d+)\s*reps$""").matchEntire(entry)?.let { match ->
        return "Step ${match.groupValues[1]}: ${match.groupValues[2]} kg x ${match.groupValues[3]} reps"
    }
    return entry
        .replace(" seconds rest", " s rest")
}

private fun compactCoachingSignalLines(lines: List<String>): List<String> {
    return lines
        .mapNotNull { line ->
            when {
                line.contains("below_best_to_date") -> "- Vs best: below"
                line.contains("best_to_date") -> "- Vs best: matched"
                line.contains("progression_state:") ->
                    line.substringAfter("progression_state:", "")
                        .takeIf { it.isNotBlank() }
                        ?.let { "- State: ${it.replace('_', ' ')}" }
                line.contains("vs_expected:above") -> "- Vs target: above"
                line.contains("vs_expected:below") -> "- Vs target: below"
                line.contains("vs_expected:equal") -> "- Vs target: equal"
                line.contains("vs_expected:mixed") -> "- Vs target: mixed"
                line.contains("vs_previous_successful_baseline:above") ->
                    "- Vs success baseline: above"
                line.contains("vs_previous_successful_baseline:below") ->
                    "- Vs success baseline: below"
                line.contains("vs_previous_successful_baseline:equal") ->
                    "- Vs success baseline: equal"
                line.contains("vs_previous_successful_baseline:mixed") ->
                    "- Vs success baseline: mixed"
                line.contains("vs_previous_session:above") -> "- Vs prev: above"
                line.contains("vs_previous_session:below") -> "- Vs prev: below"
                line.contains("vs_previous_session:similar") -> "- Vs prev: similar"
                line.contains("trend:up") -> "- Trend: up"
                line.contains("trend:down") -> "- Trend: down"
                line.contains("trend:stable") -> "- Trend: stable"
                line.contains("trend:mixed") -> "- Trend: mixed"
                line.startsWith("- Vs prev:") -> line
                line.startsWith("- Vs best:") -> line
                line.startsWith("- Trend:") -> line
                line.startsWith("- State:") -> line
                line.equals("- None", ignoreCase = true) -> null
                else -> null
            }
        }
        .distinct()
        .take(4)
}

private fun compactRepeatedEntryListLine(
    line: String,
): String {
    val prefix = listOf("- Set summary:", "- Expected:", "- Executed:")
        .firstOrNull { line.startsWith(it) } ?: return line
    val value = line.removePrefix(prefix).trim()
    if (value.isBlank()) return line
    return "$prefix ${compactRepeatedEntryList(value)}"
}

private fun compactRepeatedEntryList(
    value: String,
): String {
    val entries = value
        .split(',')
        .map { it.trim() }
        .filter { it.isNotBlank() }
    if (entries.isEmpty()) return value.trim()

    val compacted = mutableListOf<String>()
    var currentEntry = entries.first()
    var currentCount = 1

    fun flushCurrentEntry() {
        compacted += if (currentCount > 1) {
            "$currentEntry ($currentCount sets)"
        } else {
            currentEntry
        }
    }

    entries.drop(1).forEach { entry ->
        if (entry.equals(currentEntry, ignoreCase = true)) {
            currentCount += 1
        } else {
            flushCurrentEntry()
            currentEntry = entry
            currentCount = 1
        }
    }
    flushCurrentEntry()

    return compacted.joinToString(", ")
}

private fun stripLikelyWarmupSetSummaryLine(
    line: String,
): String {
    if (!line.startsWith("- Set summary:")) return line
    val summary = line.removePrefix("- Set summary:").trim()
    val filteredSummary = stripLikelyWarmupEntries(summary)
    return if (filteredSummary == summary) line else "- Set summary: $filteredSummary"
}

private fun stripLikelyWarmupEntries(
    summary: String,
): String {
    val entries = summary
        .split(',')
        .map { it.trim() }
        .filter { it.isNotBlank() }
    if (entries.size < 3) return summary

    val parsedEntries = entries.map { entry -> entry to parseSetSummaryLoad(entry) }
    val maxLoad = parsedEntries.maxOfOrNull { it.second ?: Double.NEGATIVE_INFINITY }
        ?.takeIf { it.isFinite() }
        ?: return summary

    val firstTopLoadIndex = parsedEntries.indexOfFirst { (_, load) -> load == maxLoad }
    if (firstTopLoadIndex <= 0) return summary
    val trailingEntries = parsedEntries.drop(firstTopLoadIndex)
    if (trailingEntries.size < 2) return summary
    if (trailingEntries.any { (_, load) -> load != maxLoad }) return summary
    if (parsedEntries.take(firstTopLoadIndex).none { (_, load) -> load != null && load < maxLoad }) return summary

    return trailingEntries.joinToString(", ") { it.first }
}

private fun parseSetSummaryLoad(
    entry: String,
): Double? {
    Regex("""^body weight \+\s*([0-9.]+)\s*kg\s*x\s*\d+""", RegexOption.IGNORE_CASE)
        .find(entry)
        ?.groupValues
        ?.getOrNull(1)
        ?.toDoubleOrNull()
        ?.let { return it }

    Regex("""^([0-9.]+)\s*kg\s*x\s*\d+""", RegexOption.IGNORE_CASE)
        .find(entry)
        ?.groupValues
        ?.getOrNull(1)
        ?.toDoubleOrNull()
        ?.let { return it }

    return null
}

private fun compactAthleteContextLines(lines: List<String>): List<String> {
    return lines
        .filterNot { line ->
            line.contains("Max HR:", ignoreCase = true) ||
            line.contains("Max HR reference", ignoreCase = true)
        }
        .map(::normalizeMetricLine)
        .filter { line ->
            line.startsWith("- Age:") ||
                line.startsWith("- Weight") ||
                line.startsWith("- Resting HR")
        }
        .take(3)
        .map(::compactLabelLine)
}

private fun splitMarkdownBlocks(
    markdown: String,
    startRegex: Regex,
): List<String> {
    val matches = startRegex.findAll(markdown).toList()
    if (matches.isEmpty()) return listOf(markdown)

    val blocks = mutableListOf<String>()
    var currentIndex = 0
    for ((index, match) in matches.withIndex()) {
        if (match.range.first > currentIndex) {
            blocks += markdown.substring(currentIndex, match.range.first)
        }
        val nextIndex = matches.getOrNull(index + 1)?.range?.first ?: markdown.length
        blocks += markdown.substring(match.range.first, nextIndex)
        currentIndex = nextIndex
    }
    return blocks.map { it.trim() }.filter { it.isNotBlank() }
}

private fun String.takeWithinBudget(
    budget: Int,
): String {
    val trimmed = trim()
    if (trimmed.length <= budget) return trimmed
    val safeBudget = budget.coerceAtLeast(32)
    return trimmed
        .take(safeBudget - 1)
        .trimEnd()
        .plus("…")
}

private fun humanizeDenseMetrics(line: String): String {
    return line
        .replace('×', 'x')
        .replace("Kkg", "k kg")
        .replace(" K kg", " k kg")
        .replace(" kgx ", " kg x ")
        .replace(Regex("(?<=\\d)\\s*kgx\\s*(?=\\d)"), " kg x ")
        .replace(Regex("(?<=\\d)kg(?=\\d)"), " kg x ")
        .replace(Regex("(?<=\\d)kg\\b"), " kg")
        .replace(Regex("Vol:\\s*"), "Volume: ")
        .replace(Regex("Dur:\\s*"), "Duration: ")
        .replace(Regex("Range:\\s*(\\d{4,6})\\s*bpm")) { match ->
            expandCompactBpmRange(match.groupValues[1])
                ?.let { "Range: $it bpm" }
                ?: match.value
        }
        .replace(Regex("\\((\\d{2,3})[–-](\\d{2,3})\\)"), "(range $1 to $2)")
        .replace(Regex("\\((\\d{4,6})\\)")) { match ->
            expandCompactBpmRange(match.groupValues[1])
                ?.let { "(range $it)" }
                ?: match.value
        }
        .replace(Regex("MinMax:\\s*(\\d{4,6})\\s*bpm")) { match ->
            expandCompactBpmRange(match.groupValues[1])
                ?.let { "Range: $it bpm" }
                ?: match.value
        }
        .replace(Regex("([0-9])([A-Za-z])"), "$1 $2")
        .replace(Regex("([A-Za-z])([0-9])"), "$1 $2")
        .replace(Regex("""\bZ\s+([0-9])\b"""), "Z$1")
        .replace(Regex("\\s+"), " ")
        .trim()
}

private fun normalizeRenderedPromptMetrics(line: String): String {
    return normalizeMetricLine(line)
        .replace(
            Regex("""\bVolume:\s*([0-9]+(?:\.[0-9]+)?)\s*k kg\b""", RegexOption.IGNORE_CASE)
        ) { match ->
            val kilograms = (match.groupValues[1].toDoubleOrNull()?.times(1000.0))
                ?.let(::formatKilogramVolume)
                ?: return@replace match.value
            "Volume: $kilograms kg"
        }
}

private fun formatKilogramVolume(kilograms: Double): String {
    val rounded = kilograms.roundToInt()
    return if (abs(kilograms - rounded) < 0.0001) {
        rounded.toString()
    } else {
        kilograms.toString()
    }
}

private fun normalizeMetricLine(line: String): String {
    return humanizeDenseMetrics(normalizeCompactRangeLine(normalizeDecimalComma(line)))
}

private fun normalizeDecimalComma(line: String): String {
    return line.replace(Regex("(?<=\\d),(?=\\d)"), ".")
}

private fun expandCompactBpmRange(rawRange: String): String? {
    val digits = rawRange.filter(Char::isDigit)
    if (digits.length !in 4..6) return null

    val candidates = (2..digits.length - 2).mapNotNull { splitIndex ->
        val start = digits.substring(0, splitIndex).toIntOrNull() ?: return@mapNotNull null
        val end = digits.substring(splitIndex).toIntOrNull() ?: return@mapNotNull null
        if (start !in 30..250 || end !in 30..250 || end < start) return@mapNotNull null
        start to end
    }

    val bestCandidate = candidates.minByOrNull { (start, end) -> end - start } ?: return null
    return "${bestCandidate.first} to ${bestCandidate.second}"
}

private fun executedLinePriority(line: String): Int = when {
    line.startsWith("- Date:") -> 0
    line.startsWith("- Set summary:") -> 1
    line.startsWith("- Total volume:") -> 2
    line.startsWith("- Total duration:") -> 3
    else -> 9
}

private fun historicalLinePriority(line: String): Int = when {
    line.startsWith("- Set summary:") -> 0
    line.startsWith("- Total volume:") -> 1
    line.startsWith("- Total duration:") -> 2
    line.startsWith("- Progression state:") -> 3
    else -> 9
}

private fun recoveryLinePriority(line: String): Int = when {
    line.startsWith("- Work HR:") -> 0
    line.startsWith("- Rest HR:") -> 1
    line.startsWith("- Work samples in target zone:") -> 2
    else -> 9
}

private fun sessionHeartRateLinePriority(line: String): Int = when {
    line.startsWith("- Mean:") -> 0
    line.startsWith("- Range:") -> 1
    line.startsWith("- Avg % max HR:") -> 2
    line.startsWith("- Peak % max HR:") -> 3
    line.startsWith("- High-intensity exposure:") -> 4
    line.startsWith("- Approx zone time:") -> 5
    else -> 9
}

private fun exerciseContextLinePriority(line: String): Int = when {
    line.startsWith("- Type:") -> 0
    line.startsWith("- Rep range:") -> 1
    line.startsWith("- Load range:") -> 2
    line.startsWith("- Progression mode:") -> 3
    line.startsWith("- Exercise target zone:") -> 4
    line.startsWith("- Equipment:") -> 5
    line.startsWith("- Intra-set rest:") -> 6
    line.startsWith("- Warm-up sets:") -> 7
    line.startsWith("- Notes:") -> 8
    else -> 9
}

private enum class SnapshotMetricKind {
    VOLUME,
    DURATION,
}

private data class SnapshotMetric(
    val rendered: String,
    val kind: SnapshotMetricKind,
    val numericValue: Double?,
)

private fun extractCompactValue(
    lines: List<String>,
    label: String,
): String? {
    return lines.firstNotNullOfOrNull { line ->
        if (!line.startsWith(label)) return@firstNotNullOfOrNull null
        line
            .removePrefix(label)
            .removePrefix(":")
            .trim()
            .takeIf { it.isNotBlank() }
    }
}

private fun buildSnapshotMetric(
    prefix: String,
    lines: List<String>,
): SnapshotMetric? {
    extractCompactValue(lines, "- Volume")?.let { value ->
        return SnapshotMetric(
            rendered = "$prefix vol $value",
            kind = SnapshotMetricKind.VOLUME,
            numericValue = parseSnapshotMetricNumericValue(
                value = value,
                kind = SnapshotMetricKind.VOLUME
            )
        )
    }
    extractCompactValue(lines, "- Duration")?.let { value ->
        return SnapshotMetric(
            rendered = "$prefix dur $value",
            kind = SnapshotMetricKind.DURATION,
            numericValue = parseSnapshotMetricNumericValue(
                value = value,
                kind = SnapshotMetricKind.DURATION
            )
        )
    }
    return null
}

private fun parseSnapshotMetricNumericValue(
    value: String,
    kind: SnapshotMetricKind,
): Double? {
    return when (kind) {
        SnapshotMetricKind.VOLUME -> parseVolumeMetricKg(value)
        SnapshotMetricKind.DURATION -> parseDurationMetricSeconds(value)
    }
}

private fun parseVolumeMetricKg(
    value: String,
): Double? {
    val normalized = value.lowercase().replace(" ", "")
    return when {
        normalized.endsWith("kkg") ->
            normalized.removeSuffix("kkg").toDoubleOrNull()?.times(1_000.0)
        normalized.endsWith("kg") ->
            normalized.removeSuffix("kg").toDoubleOrNull()
        else -> null
    }
}

private fun parseDurationMetricSeconds(
    value: String,
): Double? {
    val parts = value.trim().split(':').map { it.toIntOrNull() ?: return null }
    val totalSeconds = when (parts.size) {
        2 -> parts[0] * 60 + parts[1]
        3 -> parts[0] * 3_600 + parts[1] * 60 + parts[2]
        else -> return null
    }
    return totalSeconds.toDouble()
}

private fun deriveSnapshotComparisonStatus(
    current: SnapshotMetric?,
    reference: SnapshotMetric?,
): String? {
    if (current == null || reference == null || current.kind != reference.kind) return null
    val currentValue = current.numericValue ?: return null
    val referenceValue = reference.numericValue ?: return null
    return when {
        abs(currentValue - referenceValue) < 0.0001 -> "matched"
        currentValue > referenceValue -> "above"
        else -> "below"
    }
}

private fun extractBestSignalStatus(
    signalLines: List<String>,
): String? {
    return when {
        signalLines.any { it.equals("- Vs best: above", ignoreCase = true) } -> "above"
        signalLines.any { it.equals("- Vs best: matched", ignoreCase = true) } -> "matched"
        signalLines.any { it.equals("- Vs best: below", ignoreCase = true) } -> "below"
        else -> null
    }
}

private fun normalizeWorkoutSectionComparisonSignals(
    section: CompactWorkoutSectionData,
): CompactWorkoutSectionData {
    val executedLines = section.subsections.firstOrNull { it.title == "Executed" }?.lines.orEmpty()
    val previousLines = section.subsections.firstOrNull { it.title == "Previous Session" }?.lines.orEmpty()
    val bestLines = section.subsections.firstOrNull { it.title == "Best To Date" }?.lines.orEmpty()
    val derivedPreviousStatus = deriveSnapshotComparisonStatus(
        current = buildSnapshotMetric("Exec", executedLines),
        reference = buildSnapshotMetric("Prev", previousLines)
    )
    val derivedBestStatus = deriveSnapshotComparisonStatus(
        current = buildSnapshotMetric("Exec", executedLines),
        reference = buildSnapshotMetric("Best", bestLines)
    )
    val topLoadComparisonLine = buildTopLoadComparisonLine(executedLines, previousLines)
    val loadProfileComparisonLine = buildLoadProfileComparisonLine(executedLines, previousLines)
    val topLoadSetCountLine = buildTopLoadSetCountLine(executedLines, previousLines)
    if (
        derivedPreviousStatus == null &&
        derivedBestStatus == null &&
        topLoadComparisonLine == null &&
        loadProfileComparisonLine == null &&
        topLoadSetCountLine == null
    ) return pruneRedundantComparisonSubsections(section)

    val normalizedSection = section.copy(
        subsections = section.subsections.map { subsection ->
            if (subsection.title != "Coaching Signals") {
                subsection
            } else {
                subsection.copy(
                    lines = normalizeComparisonSignalLines(
                        lines = subsection.lines,
                        derivedPreviousStatus = derivedPreviousStatus,
                        derivedBestStatus = derivedBestStatus,
                        topLoadComparisonLine = topLoadComparisonLine,
                        loadProfileComparisonLine = loadProfileComparisonLine,
                        topLoadSetCountLine = topLoadSetCountLine
                    )
                )
            }
        }
    )
    return pruneRedundantComparisonSubsections(normalizedSection)
}

private fun pruneRedundantComparisonSubsections(
    section: CompactWorkoutSectionData,
): CompactWorkoutSectionData {
    val executedLines = section.subsections.firstOrNull { it.title == "Executed" }?.lines.orEmpty()
    if (executedLines.isEmpty()) return section

    val signalLines = section.subsections.firstOrNull { it.title == "Coaching Signals" }?.lines.orEmpty()
    val previousStatus = signalLines.firstOrNull { it.startsWith("- Vs prev:") }
        ?.substringAfter(':')
        ?.trim()
    val bestStatus = signalLines.firstOrNull { it.startsWith("- Vs best:") }
        ?.substringAfter(':')
        ?.trim()

    return section.copy(
        subsections = section.subsections.filterNot { subsection ->
            when (subsection.title) {
                "Previous Session" -> previousStatus == "matched" &&
                    isRedundantComparisonSnapshot(executedLines, subsection.lines)
                "Best To Date" -> bestStatus == "matched" &&
                    isRedundantComparisonSnapshot(executedLines, subsection.lines)
                else -> false
            }
        }
    )
}

private fun isRedundantComparisonSnapshot(
    executedLines: List<String>,
    comparisonLines: List<String>,
): Boolean {
    if (comparisonLines.isEmpty()) return false
    if (comparisonLines.any { it.equals("- No previous session", ignoreCase = true) }) return false
    if (executedLines == comparisonLines) return true

    val executedSnapshot = buildSnapshotMetric("Exec", executedLines)
    val comparisonSnapshot = buildSnapshotMetric("Cmp", comparisonLines)
    if (
        executedSnapshot != null &&
        comparisonSnapshot != null &&
        executedSnapshot.kind == comparisonSnapshot.kind &&
        executedSnapshot.numericValue != null &&
        comparisonSnapshot.numericValue != null &&
        abs(executedSnapshot.numericValue - comparisonSnapshot.numericValue) < 0.0001
    ) {
        return true
    }

    val comparisonDuration = extractCompactValue(comparisonLines, "- Duration")
    val executedSetDurations = extractRepeatedSetDurations(executedLines)
    return comparisonDuration != null &&
        executedSetDurations.isNotEmpty() &&
        executedSetDurations.distinct().singleOrNull() == comparisonDuration
}

private fun extractRepeatedSetDurations(
    lines: List<String>,
): List<String> {
    val setsPayload = extractCompactValue(lines, "- Sets") ?: return emptyList()
    return setsPayload
        .split('|')
        .map { it.trim() }
        .mapNotNull { entry ->
            entry.takeIf { it.startsWith("Duration:", ignoreCase = true) }
                ?.substringAfter(':')
                ?.trim()
                ?.takeIf { it.isNotBlank() }
        }
}

private fun normalizeComparisonSignalLines(
    lines: List<String>,
    derivedPreviousStatus: String?,
    derivedBestStatus: String?,
    topLoadComparisonLine: String?,
    loadProfileComparisonLine: String?,
    topLoadSetCountLine: String?,
): List<String> {
    val normalized = lines
        .map { line ->
            when {
                line.startsWith("- Vs prev:") && derivedPreviousStatus != null ->
                    "- Vs prev: $derivedPreviousStatus"
                (
                    line.equals("- Vs best: above", ignoreCase = true) ||
                        line.equals("- Vs best: matched", ignoreCase = true) ||
                        line.equals("- Vs best: below", ignoreCase = true)
                    ) && derivedBestStatus != null -> bestStatusToSignalLine(derivedBestStatus)
                else -> line
            }
        }
        .distinct()

    val insertionIndex = normalized.indexOfFirst { it.startsWith("- Vs prev:") }
    return buildList {
        normalized.forEachIndexed { index, line ->
            add(line)
            if (index == insertionIndex) {
                addIfMissing(loadProfileComparisonLine)
                addIfMissing(topLoadComparisonLine)
                addIfMissing(topLoadSetCountLine)
            }
        }
        if (insertionIndex < 0) {
            addIfMissing(loadProfileComparisonLine)
            addIfMissing(topLoadComparisonLine)
            addIfMissing(topLoadSetCountLine)
        }
    }.distinct()
}

private fun MutableList<String>.addIfMissing(
    line: String?,
) {
    if (line != null && none { it.equals(line, ignoreCase = true) }) {
        add(line)
    }
}

private fun bestStatusToSignalLine(
    bestStatus: String,
): String = when (bestStatus) {
    "above" -> "- Vs best: above"
    "matched" -> "- Vs best: matched"
    "below" -> "- Vs best: below"
    else -> "- Vs best: $bestStatus"
}

private fun buildTopLoadComparisonLine(
    executedLines: List<String>,
    previousLines: List<String>,
): String? {
    val executedLoads = extractSetLoads(executedLines) ?: return null
    val previousLoads = extractSetLoads(previousLines) ?: return null
    val executedTopLoad = executedLoads.maxOrNull() ?: return null
    val previousTopLoad = previousLoads.maxOrNull() ?: return null
    val status = when {
        abs(executedTopLoad - previousTopLoad) < 0.0001 -> "matched"
        executedTopLoad > previousTopLoad -> "above"
        else -> "below"
    }
    return "- Top load vs prev: $status (${formatLoadValue(executedTopLoad)} kg vs ${formatLoadValue(previousTopLoad)} kg)"
}

private fun buildLoadProfileComparisonLine(
    lines: List<String>,
    previousLines: List<String>,
): String? {
    val executedLoads = extractSetLoads(lines) ?: return null
    val previousLoads = extractSetLoads(previousLines) ?: return null
    val pairCount = minOf(executedLoads.size, previousLoads.size)
    if (pairCount == 0) return null

    var aboveCount = 0
    var belowCount = 0
    var matchedCount = 0
    repeat(pairCount) { index ->
        val diff = executedLoads[index] - previousLoads[index]
        when {
            abs(diff) < 0.0001 -> matchedCount += 1
            diff > 0 -> aboveCount += 1
            else -> belowCount += 1
        }
    }

    val status = when {
        aboveCount > 0 && belowCount > 0 -> "mixed"
        aboveCount > 0 && matchedCount > 0 -> "mixed"
        belowCount > 0 && matchedCount > 0 -> "mixed"
        aboveCount > 0 -> "above"
        belowCount > 0 -> "below"
        executedLoads.size == previousLoads.size -> "matched"
        executedLoads.size > previousLoads.size -> "mixed"
        else -> "mixed"
    }
    return "- Load profile vs prev: $status"
}

private fun buildTopLoadSetCountLine(
    executedLines: List<String>,
    previousLines: List<String>,
): String? {
    val executedLoads = extractSetLoads(executedLines) ?: return null
    val previousLoads = extractSetLoads(previousLines) ?: return null
    val executedTopLoad = executedLoads.maxOrNull() ?: return null
    val previousTopLoad = previousLoads.maxOrNull() ?: return null
    val executedTopLoadCount = executedLoads.count { abs(it - executedTopLoad) < 0.0001 }
    val previousTopLoadCount = previousLoads.count { abs(it - previousTopLoad) < 0.0001 }
    return "- Sets at top load: $executedTopLoadCount vs $previousTopLoadCount"
}

private fun extractSetLoads(
    lines: List<String>,
): List<Double>? {
    val setsLine = lines.firstOrNull { it.startsWith("- Sets:") } ?: return null
    return setsLine
        .removePrefix("- Sets:")
        .split(',')
        .map { it.trim() }
        .flatMap(::expandSetEntryLoads)
        .ifEmpty { null }
}

private fun formatLoadValue(
    load: Double,
): String {
    val rounded = load.roundToInt().toDouble()
    return if (abs(load - rounded) < 0.0001) {
        rounded.roundToInt().toString()
    } else {
        load.toString()
    }
}

private fun expandSetEntryLoads(
    entry: String,
): List<Double> {
    val load = parseSetSummaryLoad(entry) ?: return emptyList()
    val count = Regex("""\((\d+)\s+sets\)""", RegexOption.IGNORE_CASE)
        .find(entry)
        ?.groupValues
        ?.getOrNull(1)
        ?.toIntOrNull()
        ?: 1
    return List(count) { load }
}

private fun signalValueToPlanStatus(value: String?): String? {
    return when (value?.lowercase()) {
        "equal" -> "met"
        "above" -> "above"
        "below" -> "below"
        "mixed" -> "mixed"
        else -> value
    }
}

private fun signalValueToComparisonStatus(value: String?): String? {
    return when (value?.lowercase()) {
        "equal" -> "matched"
        "above" -> "above"
        "below" -> "below"
        "mixed" -> "mixed"
        "similar" -> "similar"
        else -> value
    }
}

private fun buildApproxZoneTimeLine(lines: List<String>): String? {
    val validSampleCount = lines.firstNotNullOfOrNull(::parseValidHeartRateSampleCount)
        ?: lines.firstNotNullOfOrNull(::parseRecordedHeartRateSpanSeconds)
        ?: return null
    val zoneDurations = lines
        .mapNotNull(::parseHeartRateZoneFraction)
        .mapNotNull { (zoneLabel, percent) ->
            val estimatedSeconds = (validSampleCount * percent.toDouble() / 100.0).toInt()
            if (estimatedSeconds <= 0) null else "$zoneLabel ${formatApproxDuration(estimatedSeconds)}"
        }
    if (zoneDurations.isEmpty()) return null
    return "- Approx zone time: ${zoneDurations.joinToString(" | ")}"
}

private fun parseValidHeartRateSampleCount(
    line: String,
): Int? {
    return Regex("""^- Valid HR samples:\s*(\d+)""", RegexOption.IGNORE_CASE)
        .find(line.trim())
        ?.groupValues
        ?.getOrNull(1)
        ?.toIntOrNull()
}

private fun parseRecordedHeartRateSpanSeconds(
    line: String,
): Int? {
    val duration = Regex(
        """Approx\.\s+recorded\s+HR\s+span.*:\s*(\d{2}:\d{2}(?::\d{2})?)""",
        RegexOption.IGNORE_CASE
    ).find(line)?.groupValues?.getOrNull(1) ?: return null
    val parts = duration.split(":").mapNotNull { it.toIntOrNull() }
    return when (parts.size) {
        2 -> parts[0] * 60 + parts[1]
        3 -> parts[0] * 3600 + parts[1] * 60 + parts[2]
        else -> null
    }
}

private fun parseHeartRateZoneFraction(
    line: String,
): Pair<String, Int>? {
    val match = Regex(
        """^- Z\s*(\d+)\s*\([^)]*\):\s*(\d{1,3})%\s+of\s+samples""",
        RegexOption.IGNORE_CASE
    ).find(line.trim()) ?: return null
    return "Z${match.groupValues[1]}" to (match.groupValues[2].toIntOrNull() ?: return null)
}

private fun formatApproxDuration(
    totalSeconds: Int,
): String {
    val hours = totalSeconds / 3600
    val minutes = (totalSeconds % 3600) / 60
    val seconds = totalSeconds % 60
    return if (hours > 0) {
        "%d:%02d:%02d".format(hours, minutes, seconds)
    } else {
        "%02d:%02d".format(minutes, seconds)
    }
}

private fun renderCompactWorkoutSection(
    section: CompactWorkoutSectionData,
): String = buildString {
    append(compactWorkoutSectionHeading(section.heading))
    append('\n')
    append(section.subsections.joinToString("\n") { subsection ->
        renderStructuredSubsection(subsection.title, subsection.lines)
    })
}.trim().takeWithinBudget(MAX_SECTION_CHAR_BUDGET)

private fun List<String>.takeWhileBudget(
    budget: Int,
): List<String> {
    var consumed = 0
    val result = mutableListOf<String>()
    for (line in this) {
        val next = consumed + line.length + 1
        if (next > budget && result.isNotEmpty()) break
        result += line
        consumed = next
    }
    return result
}

private fun buildWorkoutCategoryContextLine(
    workoutType: Int,
): String = "Workout category: ${WorkoutTypes.GetNameFromInt(workoutType)}"

private fun buildWorkoutCategoryPromptGuidance(
    workoutType: Int,
): String {
    return when (classifyWorkoutPromptCategory(workoutType)) {
        WorkoutPromptCategory.STRENGTH ->
            "Category guidance: judge success mainly from lift performance, progression, and recovery, with HR as supporting context only."
        WorkoutPromptCategory.CONDITIONING ->
            "Category guidance: judge success mainly from interval execution, intensity distribution, and repeatability, with HR as a primary effort signal."
        WorkoutPromptCategory.ENDURANCE ->
            "Category guidance: judge success mainly from sustained effort, pacing consistency, and aerobic load, with HR as a primary effort signal."
        WorkoutPromptCategory.MOBILITY ->
            "Category guidance: judge success mainly from completion quality and recovery intent, not from pushing intensity."
        WorkoutPromptCategory.GENERAL ->
            "Category guidance: balance performance, effort, and recovery signals according to the workout type."
    }
}

private fun buildWorkoutStructurePromptGuidance(
    workoutCategoryLine: String,
    markdown: String,
): String? {
    if (!workoutCategoryLine.contains("Workout category: Workout", ignoreCase = true)) return null
    val exerciseTypes = Regex("""\bCONTEXT Type ([A-Z_]+)""")
        .findAll(markdown)
        .map { it.groupValues[1] }
        .toList()
    if (exerciseTypes.isEmpty()) return null

    val liftingTypes = setOf("WEIGHT", "BODY_WEIGHT", "ASSISTED_BODY_WEIGHT")
    val liftingTypeCount = exerciseTypes.count { it in liftingTypes }
    if (liftingTypeCount * 2 < exerciseTypes.size) return null

    return "Exercise mix guidance: this session is lifting-dominant even though the workout category label is generic, so judge success mainly from exercise performance and recovery, with HR as supporting context only."
}

private enum class WorkoutPromptCategory {
    STRENGTH,
    CONDITIONING,
    ENDURANCE,
    MOBILITY,
    GENERAL,
}

private fun classifyWorkoutPromptCategory(
    workoutType: Int,
): WorkoutPromptCategory {
    val typeName = WorkoutTypes.GetNameFromInt(workoutType).lowercase()
    return when {
        typeName == "strength training" || typeName == "weightlifting" -> WorkoutPromptCategory.STRENGTH
        typeName == "high intensity interval training" ||
            typeName == "biking stationary" ||
            typeName == "rowing machine" ||
            typeName == "boot camp" -> WorkoutPromptCategory.CONDITIONING
        typeName in setOf(
            "running",
            "running treadmill",
            "biking",
            "rowing",
            "walking",
            "stair climbing",
            "stair climbing machine",
            "swimming pool",
            "swimming open water",
            "elliptical",
            "hiking"
        ) -> WorkoutPromptCategory.ENDURANCE
        typeName in setOf("yoga", "pilates", "stretching", "guided breathing") -> WorkoutPromptCategory.MOBILITY
        else -> WorkoutPromptCategory.GENERAL
    }
}

private fun normalizeCompactRangeLine(
    line: String,
): String {
    val rangeMatch = Regex("""(?i)(\bRange:\s*)(\d{4,6})(\s*bpm\b)""").find(line) ?: return line
    val expanded = expandCompactBpmRange(rangeMatch.groupValues[2]) ?: return line
    return line.replaceRange(rangeMatch.range, "${rangeMatch.groupValues[1]}$expanded bpm")
}

private fun compactLabelLine(
    line: String,
): String {
    return line
        .replace("- Total volume:", "- Volume:")
        .replace("- Total duration:", "- Duration:")
        .replace("- Set summary:", "- Sets:")
        .replace("- Progression state:", "- State:")
        .replace("- Expected:", "- Expected:")
        .replace("- Executed:", "- Executed:")
        .replace("- Vs expected:", "- Vs expected:")
        .replace("- Vs previous baseline:", "- Vs success baseline:")
        .replace("- Work samples in target zone:", "- In target zone:")
        .replace("- High-intensity exposure:", "- High-intensity exposure:")
        .replace("- Avg % max HR:", "- Avg % max HR:")
        .replace("- Peak % max HR:", "- Peak % max HR:")
        .replace("- Avg % HR reserve:", "- Avg % HR reserve:")
        .replace("- Peak % HR reserve:", "- Peak % HR reserve:")
        .replace("- Type:", "- Type")
        .replace("- Equipment:", "- Equipment")
        .replace("- Rep range:", "- Rep range")
        .replace("- Load range:", "- Load range")
        .replace("- Progression mode:", "- Progression")
        .replace("- Exercise target zone:", "- Target zone")
        .replace("- Intra-set rest:", "- Intra-set rest")
        .replace("- Warm-up sets:", "- Warm-up")
        .replace("- Resting HR (bpm):", "- Rest HR:")
        .replace("- Weight (kg):", "- Body weight:")
}

private fun compactExerciseSessionHeading(
    heading: String,
): String = heading
    .removePrefix("## ")
    .replaceFirst(": ", " ")

private fun compactWorkoutSectionHeading(
    heading: String,
): String = when {
    heading.startsWith("### Superset: ") -> "SUPERSET ${heading.removePrefix("### Superset: ").trim()}"
    heading.startsWith("### ") -> "EXERCISE ${heading.removePrefix("### ").trim()}"
    else -> heading.trim()
}

private fun normalizePromptLayout(
    prompt: String,
): String = prompt
    .lines()
    .joinToString("\n") { it.trimStart().trimEnd() }
    .replace(Regex("""\n{3,}"""), "\n\n")
    .trim()

private fun compactStructuredMetadataLine(
    line: String,
): String = line
    .removePrefix("- ")
    .replace("Template position:", "slot=")
    .replace("exercise ", "")
    .replace(" of ", "/")
    .replace(" (flattened workout order)", "")
    .replace("Session BW:", "bw=")

private fun renderStructuredSubsection(
    title: String,
    lines: List<String>,
): String {
    val payload = lines.joinToString(" | ") { it.removePrefix("- ").trim() }
    val normalizedPayload = normalizeRenderedPromptMetrics(payload)
    return "${structuredTag(title)} $normalizedPayload".trim()
}

private fun structuredTag(
    title: String,
): String = when (title) {
    "Context" -> "CONTEXT"
    "Planned" -> "PLAN"
    "Athlete Context" -> "ATHLETE"
    "Session Heart Rate" -> "HR"
    "Executed" -> "EXEC"
    "Previous Session" -> "PREV"
    "Best To Date" -> "BEST"
    "Recovery Context" -> "RECOVERY"
    "Coaching Signals" -> "SIGNALS"
    "Progression Context" -> "PROG"
    "Executed Timeline" -> "TIMELINE"
    else -> title.uppercase()
}

internal fun estimateTokenCount(
    text: String,
): Int {
    val trimmed = text.trim()
    if (trimmed.isEmpty()) return 0
    val scaledLength = trimmed.length * ESTIMATED_CHARS_PER_TOKEN_DENOMINATOR
    return (scaledLength + ESTIMATED_CHARS_PER_TOKEN_NUMERATOR - 1) /
        ESTIMATED_CHARS_PER_TOKEN_NUMERATOR
}
