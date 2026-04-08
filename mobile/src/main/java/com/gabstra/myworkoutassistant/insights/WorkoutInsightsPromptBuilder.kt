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
private const val MAX_SESSION_HR_LINES = 5

internal const val WORKOUT_INSIGHTS_SYSTEM_PROMPT = """
You are an on-device workout insights assistant.
Use only the supplied workout history.
Do not invent data.
Do not provide medical advice or diagnose injuries.
If the history is sparse or inconsistent, say so plainly.
Base intensity claims on the supplied HR cues, especially Avg % max HR, Peak % max HR, High-intensity exposure, work HR, rest HR, and recovery gap.
Do not call a session high-intensity if High-intensity exposure is low and Avg % max HR is modest.
Treat best-to-date or progression signals as performance context, not proof of high fatigue or high intensity by themselves.
If evidence is mixed, prefer a cautious interpretation.
For strength workouts, do not prescribe higher heart rate as the main goal; prioritize load, reps, execution quality, and recovery instead.
Use HR mainly to describe overall effort, density, and recovery, not as the primary target for barbell progression.
Do not turn a low-intensity lifting session into a problem unless the performance data also suggests under-stimulation or drift from plan.
Avoid generic advice that could apply to any workout; anchor each point to the most relevant lifts or session signals.
In Risks, only mention a meaningful downside or constraint, not a neutral restatement of the data.
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
"""

sealed class WorkoutInsightsPromptResult {
    data class Success(
        val title: String,
        val prompt: String,
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
                prompt = buildExercisePrompt(markdownResult.markdown)
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
                )
            )
        }
    }
}

internal fun buildExercisePrompt(
    markdown: String,
): String = buildPromptWithinBudget { charBudget ->
    val compactedMarkdown = compactExerciseHistoryMarkdown(
        markdown = markdown,
        markdownCharBudget = charBudget
    )
    """
Analyze this exercise history and provide focused training insights.
Prioritize progression, stalling signals, recovery patterns, and the clearest next-session recommendation.
Be concise: at most 2 short bullets per required section.
Ground every point in the supplied data.

Exercise history:
$compactedMarkdown
    """.trimIndent()
}

internal fun buildWorkoutSessionPrompt(
    markdown: String,
    workoutCategoryGuidance: String,
    workoutCategoryLine: String,
): String = buildPromptWithinBudget { charBudget ->
    val compactedMarkdown = compactWorkoutSessionMarkdown(
        markdown = markdown,
        markdownCharBudget = charBudget
    )
    """
Analyze this completed workout session and provide practical coaching insights.
Focus on what went well, what drifted from plan, likely fatigue/recovery signals, and one clear recommendation for the next session.
Be concise: at most 2 short bullets per required section.
Use HR cues carefully: low High-intensity exposure and modest Avg % max HR usually indicate a low-to-moderate intensity session.
Do not infer high fatigue or high intensity from volume alone.
For lifting sessions, do not recommend chasing a higher Avg % max HR unless the workout is explicitly conditioning-focused.
Prioritize the primary lifts and compare executed performance against previous and best-to-date performance.
If several accessories improved but one main lift regressed, say that explicitly instead of flattening everything into one summary.
Ground every point in the supplied data.
${workoutCategoryGuidance.trimEnd()}

Workout session:
${workoutCategoryLine}$compactedMarkdown
    """.trimIndent()
}

private inline fun buildPromptWithinBudget(
    promptBuilder: (markdownCharBudget: Int) -> String,
): String {
    var markdownCharBudget = TARGET_MARKDOWN_CHAR_BUDGET
    var bestPrompt = promptBuilder(markdownCharBudget)

    while (
        estimateTokenCount(WORKOUT_INSIGHTS_SYSTEM_PROMPT) + estimateTokenCount(bestPrompt) >
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
            line.startsWith("- Avg %maxHR:") ||
                line.startsWith("- Peak %maxHR:") ||
                line.startsWith("- Hi exp:")
        }
        .filterNot { line ->
            line == "- Hi exp: 0% of samples"
        }
        .take(2)

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
                line.startsWith("- Note:") ||
                line.startsWith("- Volume: Prev")
        }
        .map { line ->
            line
                .replace("- State:", "- Progression state:")
                .replace("- Comparison vs expected:", "- Vs expected:")
                .replace("- Comparison vs previous successful baseline:", "- Vs previous baseline:")
        }
        .map(::normalizeCompactRangeLine)
        .map(::humanizeDenseMetrics)
        .filter { line ->
            line.startsWith("- Progression state:") ||
                line.startsWith("- Expected:") ||
                line.startsWith("- Executed:") ||
                line.startsWith("- Vs expected:") ||
                line.startsWith("- Volume:")
        }
        .map(::compactLabelLine)
        .take(5)

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
    val sections = blocks.drop(1)
    val compactSections = aggregateRepeatedWorkoutSections(
        sections.mapNotNull { compactWorkoutSectionData(it) }
    )
    val omittedCount = sections.size - compactSections.size

    val compacted = buildString {
        append(header)
        append("\n\n")
        append("_Timelines and trends trimmed._")
        append("\n\n")
        append(compactSections.joinToString("\n\n") { renderCompactWorkoutSection(it) })
    }.trim()

    if (compacted.length <= markdownCharBudget) return compacted

    val reducedSections = compactSections.map { renderCompactWorkoutSection(it).takeWithinBudget(MAX_SECTION_CHAR_BUDGET) }
    return buildString {
        append(header.takeWithinBudget(MAX_SECTION_CHAR_BUDGET))
        append("\n\n")
        append("_Timelines, trends, and low-priority lines trimmed._\n\n")
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

    return CompactWorkoutSectionData(
        heading = heading,
        subsections = keptSubsections
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
        "Planned" -> compactPlannedLines(bodyLines)
        "Session Heart Rate" -> compactSessionHeartRateLines(bodyLines)
        "Executed" -> compactExecutedLines(bodyLines)
        "Previous Session", "Best To Date" -> compactHistoricalLines(bodyLines)
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
    return lines
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
            normalizeCompactRangeLine(
                line
                .replace("Min–Max:", "Range:")
                .replace("Average as % of max HR:", "Avg % max HR:")
                .replace("Peak as % of max HR:", "Peak % max HR:")
                .replace("Average as % heart-rate reserve:", "Avg % HR reserve:")
                .replace("Peak as % heart-rate reserve:", "Peak % HR reserve:")
                .replace("Time at or above 85% of max HR:", "High-intensity exposure:")
            )
        }
        .map(::humanizeDenseMetrics)
        .filter { line ->
            line.startsWith("- Mean:") ||
                line.startsWith("- Range:") ||
                line.startsWith("- Avg % max HR:") ||
                line.startsWith("- Peak % max HR:") ||
                line.startsWith("- High-intensity exposure:")
        }
        .sortedBy { sessionHeartRateLinePriority(it) }
        .take(MAX_SESSION_HR_LINES)
        .map(::compactLabelLine)
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
    return compactSignalLines(lines)
        .filter { line ->
            line.startsWith("- Total volume:") ||
                line.startsWith("- Total duration:") ||
                line.startsWith("- Set summary:") ||
                line.startsWith("- Date:")
        }
        .sortedBy { executedLinePriority(it) }
        .take(3)
        .map(::compactLabelLine)
}

private fun compactHistoricalLines(lines: List<String>): List<String> {
    return compactSignalLines(lines)
        .filter { line ->
            line.startsWith("- Total volume:") ||
                line.startsWith("- Total duration:") ||
                line.startsWith("- Set summary:") ||
                line.startsWith("- Progression state:")
        }
        .sortedBy { historicalLinePriority(it) }
        .take(3)
        .map(::compactLabelLine)
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
        .map(::humanizeDenseMetrics)
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
    val plannedSets = lines
        .map(::humanizeDenseMetrics)
        .filter { line -> line.startsWith("- P") }
        .map { line -> line.removePrefix("- ").trim() }

    if (plannedSets.isEmpty()) {
        return emptyList()
    }

    val previewCount = 4
    val preview = plannedSets.take(previewCount).joinToString("; ")
    return if (plannedSets.size > previewCount) {
        listOf("- Plan: $preview; ... (${plannedSets.size} total)")
    } else {
        listOf("- Plan: $preview")
    }
}

private fun compactCoachingSignalLines(lines: List<String>): List<String> {
    return lines
        .mapNotNull { line ->
            when {
                line.contains("best_to_date") -> "- Best to date"
                line.contains("below_best_to_date") -> "- Below best to date"
                line.contains("progression_state:") ->
                    line.substringAfter("progression_state:", "")
                        .takeIf { it.isNotBlank() }
                        ?.let { "- State: ${it.replace('_', ' ')}" }
                line.contains("vs_expected:above") -> "- Vs exp: above"
                line.contains("vs_expected:below") -> "- Vs exp: below"
                line.contains("vs_expected:equal") -> "- Vs exp: equal"
                line.contains("vs_expected:mixed") -> "- Vs exp: mixed"
                line.contains("vs_previous_successful_baseline:above") ->
                    "- Vs baseline: above"
                line.contains("vs_previous_successful_baseline:below") ->
                    "- Vs baseline: below"
                line.contains("vs_previous_successful_baseline:equal") ->
                    "- Vs baseline: equal"
                line.contains("vs_previous_successful_baseline:mixed") ->
                    "- Vs baseline: mixed"
                line.contains("vs_previous_session:above") -> "- Vs prev: above"
                line.contains("vs_previous_session:below") -> "- Vs prev: below"
                line.contains("vs_previous_session:similar") -> "- Vs prev: similar"
                line.contains("trend:up") -> "- Trend: up"
                line.contains("trend:down") -> "- Trend: down"
                line.contains("trend:stable") -> "- Trend: stable"
                line.contains("trend:mixed") -> "- Trend: mixed"
                line.equals("- None", ignoreCase = true) -> null
                else -> null
            }
        }
        .distinct()
        .take(4)
}

private fun compactAthleteContextLines(lines: List<String>): List<String> {
    return lines
        .filterNot { line ->
            line.contains("Max HR:", ignoreCase = true) ||
            line.contains("Max HR reference", ignoreCase = true)
        }
        .map(::humanizeDenseMetrics)
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
        .replace(Regex("\\s+"), " ")
        .trim()
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

private fun aggregateRepeatedWorkoutSections(
    sections: List<CompactWorkoutSectionData>,
): List<CompactWorkoutSectionData> {
    if (sections.isEmpty()) return emptyList()

    val grouped = LinkedHashMap<String, MutableList<CompactWorkoutSectionData>>()
    sections.forEach { section ->
        grouped.getOrPut(section.heading) { mutableListOf() }.add(section)
    }

    return grouped.values.map { sameHeadingSections ->
        if (sameHeadingSections.size == 1) {
            sameHeadingSections.first()
        } else {
            aggregateSectionGroup(sameHeadingSections)
        }
    }
}

private fun aggregateSectionGroup(
    sections: List<CompactWorkoutSectionData>,
): CompactWorkoutSectionData {
    val heading = sections.first().heading
    val subsectionTitles = linkedSetOf<String>().apply {
        sections.forEach { section -> section.subsections.forEach { add(it.title) } }
    }

    val aggregatedSubsections = subsectionTitles.mapNotNull { title ->
        val lines = sections.flatMap { section ->
            section.subsections.firstOrNull { it.title == title }?.lines.orEmpty()
        }
        when (title) {
            "Recovery Context" -> aggregateRecoverySubsection(title, lines, sections.size)
            "Coaching Signals" -> aggregateSimpleDedupSubsection(title, lines, sections.size)
            else -> aggregateSimpleDedupSubsection(title, lines, sections.size)
        }
    }

    return CompactWorkoutSectionData(
        heading = heading,
        subsections = aggregatedSubsections
    )
}

private fun aggregateRecoverySubsection(
    title: String,
    lines: List<String>,
    repeatCount: Int,
): CompactWorkoutSubsectionData? {
    val workAverages = mutableListOf<Int>()
    val workPeaks = mutableListOf<Int>()
    val restAverages = mutableListOf<Int>()
    val restPeaks = mutableListOf<Int>()
    val targetZonePercents = mutableListOf<Int>()

    lines.forEach { line ->
        Regex("""^- Work HR: avg (\d{2,3}) bpm \| peak (\d{2,3}) bpm$""").find(line)?.let { match ->
            workAverages += match.groupValues[1].toInt()
            workPeaks += match.groupValues[2].toInt()
            return@forEach
        }
        Regex("""^- Rest HR: avg (\d{2,3}) bpm \| peak (\d{2,3}) bpm$""").find(line)?.let { match ->
            restAverages += match.groupValues[1].toInt()
            restPeaks += match.groupValues[2].toInt()
            return@forEach
        }
        Regex("""^- In-zone: (\d{1,3})%$""").find(line)?.let { match ->
            targetZonePercents += match.groupValues[1].toInt()
        }
    }

    val aggregatedLines = mutableListOf<String>()
    if (repeatCount > 1) {
        aggregatedLines += "- Repeated $repeatCount times"
    }
    if (workAverages.isNotEmpty() && workPeaks.isNotEmpty()) {
        aggregatedLines += "- Work HR avg range: ${workAverages.min()} to ${workAverages.max()} bpm | peak range: ${workPeaks.min()} to ${workPeaks.max()} bpm"
    }
    if (restAverages.isNotEmpty() && restPeaks.isNotEmpty()) {
        aggregatedLines += "- Rest HR avg range: ${restAverages.min()} to ${restAverages.max()} bpm | peak range: ${restPeaks.min()} to ${restPeaks.max()} bpm"
    }
    if (targetZonePercents.isNotEmpty()) {
        aggregatedLines += "- In-zone range: ${targetZonePercents.min()}% to ${targetZonePercents.max()}%"
    }

    if (aggregatedLines.isEmpty()) return null
    return CompactWorkoutSubsectionData(title, aggregatedLines.take(4))
}

private fun aggregateSimpleDedupSubsection(
    title: String,
    lines: List<String>,
    repeatCount: Int,
): CompactWorkoutSubsectionData? {
    val deduped = lines.distinct()
    if (deduped.isEmpty()) return null
    val aggregatedLines = mutableListOf<String>()
    if (repeatCount > 1) {
        aggregatedLines += "- Repeated $repeatCount times"
    }
    aggregatedLines += deduped
    return CompactWorkoutSubsectionData(title, aggregatedLines.take(4))
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
    val rangeMatch = Regex("""(Range:\s*)(\d{4,6})(\s*bpm)""").find(line) ?: return line
    val expanded = expandCompactBpmRange(rangeMatch.groupValues[2]) ?: return line
    return line.replaceRange(rangeMatch.range, "${rangeMatch.groupValues[1]}$expanded${rangeMatch.groupValues[3]}")
}

private fun compactLabelLine(
    line: String,
): String {
    return line
        .replace("- Total volume:", "- Vol:")
        .replace("- Total duration:", "- Dur:")
        .replace("- Set summary:", "- Sets:")
        .replace("- Progression state:", "- State:")
        .replace("- Expected:", "- Exp:")
        .replace("- Executed:", "- Done:")
        .replace("- Vs expected:", "- Vs exp:")
        .replace("- Vs previous baseline:", "- Vs base:")
        .replace("- Work samples in target zone:", "- In-zone:")
        .replace("- High-intensity exposure:", "- Hi exp:")
        .replace("- Avg % max HR:", "- Avg %maxHR:")
        .replace("- Peak % max HR:", "- Peak %maxHR:")
        .replace("- Avg % HR reserve:", "- Avg %HRR:")
        .replace("- Peak % HR reserve:", "- Peak %HRR:")
        .replace("- Type:", "- Type")
        .replace("- Equipment:", "- Equip")
        .replace("- Rep range:", "- Reps")
        .replace("- Load range:", "- Load")
        .replace("- Progression mode:", "- Prog")
        .replace("- Exercise target zone:", "- Zone")
        .replace("- Intra-set rest:", "- Rest")
        .replace("- Warm-up sets:", "- Warm-up")
        .replace("- Resting HR (bpm):", "- Rest HR:")
        .replace("- Weight (kg):", "- Wt:")
}

private fun compactExerciseSessionHeading(
    heading: String,
): String = heading
    .removePrefix("## ")
    .replaceFirst(": ", " ")
    .replace(" | Dur: ", " | dur=")

private fun compactWorkoutSectionHeading(
    heading: String,
): String = when {
    heading.startsWith("### Superset: ") -> "SUPERSET ${heading.removePrefix("### Superset: ").trim()}"
    heading.startsWith("### ") -> "EXERCISE ${heading.removePrefix("### ").trim()}"
    else -> heading.trim()
}

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
    return "${structuredTag(title)} $payload".trim()
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
