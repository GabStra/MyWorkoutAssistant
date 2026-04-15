package com.gabstra.myworkoutassistant.insights

import com.gabstra.myworkoutassistant.WorkoutTypes
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgressionDao
import com.gabstra.myworkoutassistant.shared.RestHistoryDao
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutRecordDao
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.export.ExerciseHistoryMarkdownResult
import com.gabstra.myworkoutassistant.shared.export.WorkoutSessionMarkdownResult
import com.gabstra.myworkoutassistant.shared.export.buildExerciseHistoryMarkdown
import com.gabstra.myworkoutassistant.shared.export.buildWorkoutSessionMarkdown
import com.gabstra.myworkoutassistant.shared.workout.history.SessionTimelineItem
import com.gabstra.myworkoutassistant.shared.workout.history.mergeSessionTimeline
import com.gabstra.myworkoutassistant.shared.workout.model.WorkoutSessionStatus
import com.gabstra.myworkoutassistant.shared.workout.model.resolveWorkoutSessionStatus
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import java.time.Duration
import java.time.LocalDateTime
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

private const val FINAL_RESPONSE_NUMERIC_POLICY = """
Final-response numeric policy:
- Use exact numeric fields only to decide comparisons and coaching meaning.
- Write qualitative relationships instead, such as higher load, lower volume, matched plan, similar reps, steadier HR, or below the previous session.
- Avoid writing exact metric values with units in the final markdown, including kg, reps, set counts, bpm, percentages, pace, distance, duration, or volume.
- If an exact metric value is necessary, copy it verbatim from the supplied evidence; never transform, estimate, round, concatenate, or infer numeric values.
- If exact metric values are needed in the UI, they must come from deterministic app-rendered evidence, not model-written prose.
"""

private const val WORKOUT_INSIGHTS_SYSTEM_PROMPT_BASE = """
You are a workout insights assistant.

Goal:
Explain the workout in plain, useful coaching language.

Rules:
- Use only the evidence returned by tools.
- Do not invent data.
- Do not provide medical advice or diagnose injuries.
- If the data is sparse, trimmed, inconsistent, or the workout is incomplete, say so plainly.
- If metrics conflict, prefer the most explicit numeric fields first:
  1. explicit numeric fields such as Exec, Prev, Best, volume, duration, executed sets, reps, load, pace, distance, time
  2. progression fields such as Progression state, Vs expected, Vs previous, Vs baseline, expected sets, auto RIR
  3. session state and status labels
  4. HR cues from text metrics only
- If a status label conflicts with explicit numeric values, trust the numeric values.
- Never describe a metric as improved if the numeric value is lower than the previous value.
- If one exercise improved and another regressed or lagged versus previous, say that explicitly.
- For lifting-dominant sessions, prioritize load, reps, completed work, and exercise-by-exercise comparison; use HR only as supporting context.
- Do not call recovery inadequate from elevated HR alone.
- Avoid generic advice.
- Write for a normal user, not for an analyst.
- Prefer plain language over internal labels such as "vs baseline", "load profile", "constraint", or "drift" unless those terms are necessary.
- Translate the data into direct coaching takeaways instead of restating metric labels.

Progression knowledge:
- Double progression means the app normally adds reps at the current working load until work sets reach the top of the rep range, then raises load when a suitable heavier weight is available.
- After a double-progression load increase, lower reps or lower total volume can be expected; do not call that a regression if the session met the expected sets or clearly advanced load as planned.
- Auto-regulation uses the same double-progression baseline, then adjusts later work sets during the session from rep performance or recorded auto RIR on non-last work sets.
- For auto-regulation, around 2 RIR or reps inside the target range usually means keep the load, clearly below the minimum rep target means the load was likely too high and later sets may drop, and clearly above the maximum rep target or higher RIR means later sets may rise.
- Treat auto-regulated load changes as intended when the set data supports them; do not flatten them into inconsistency or simple volume drift.
- Progression state PROGRESS/RETRY/DELOAD/FAILED and comparisons vs expected or previous describe the app's progression decision; expected sets are the session target, and previous successful baseline is the success baseline.
- For double-progression or auto-regulated exercises, judge success against expected sets and progression comparisons before raw total volume.

Respond in markdown using these sections:
## What stood out
## Exercise highlights

Requirements:
- Use as many bullets as needed for grounded, decision-useful details.
- Do not omit grounded, decision-useful details just to satisfy brevity, but merge related exercises when one concise bullet can cover them accurately.
- Keep each bullet short, focused, and non-redundant.
- Do not repeat the same fact in multiple sections; if a section would only repeat an earlier point, skip that bullet.
- start every bullet with "- "
- no introduction or conclusion outside the required sections
- include HR when it changes or supports the interpretation, but do not let HR override clearer lifting evidence
- omit obvious filler
- do not force a negative point if the session was broadly solid

Before finalizing, silently verify:
- every claim is supported by the supplied evidence
- no bullet says something improved if the number is lower
- mixed outcomes across exercises are stated explicitly when present
- double progression and auto-regulation are interpreted as progression systems, not as generic static targets
- the wording is natural and user-friendly
"""

internal val WORKOUT_INSIGHTS_SYSTEM_PROMPT = listOf(
    WORKOUT_INSIGHTS_SYSTEM_PROMPT_BASE.trimIndent(),
    FINAL_RESPONSE_NUMERIC_POLICY.trimIndent()
).joinToString("\n\n")

private const val EXERCISE_INSIGHTS_SYSTEM_PROMPT_BASE = """
You are an exercise insights assistant.

Goal:
Explain a single exercise’s recent performance in plain, useful coaching language.

Rules:
- Use only the evidence returned by tools.
- Do not invent data.
- Do not provide medical advice or diagnose injuries.
- If the data is sparse, trimmed, inconsistent, or the latest session is not clearly completed, say so plainly.
- Focus on the latest completed session first; use recent history only where it changes the interpretation.
- Prioritize evidence in this order:
  1. explicit numeric fields such as executed vs expected sets, reps, load, volume, duration
  2. progression fields such as Progression state, Vs expected, Vs previous, Vs baseline, expected sets, auto RIR
  3. recent trend across sessions
  4. HR cues from text metrics only, as supporting context
- If a label conflicts with explicit numeric values, trust the numeric values.
- Never describe a metric as improved if the numeric value is lower than the comparison value.
- If the latest session met plan but still lagged previous, baseline, or recent trend, say that explicitly.
- If the latest session improved on one dimension but worsened on another, state that split clearly.
- For strength-oriented exercises, prioritize reps, load, completed sets, and volume.
- Use HR only as supporting context for effort, density, or recovery; do not treat it as the main progression signal unless the exercise is primarily conditioning-based.
- Mention later-set drop-off only if it meaningfully changes the interpretation.
- Avoid generic advice.
- Write for a normal user, not for an analyst.
- Prefer plain language over internal labels such as "vs baseline", "progression state", "constraint", or "drift" unless those terms are necessary.
- Translate the data into direct coaching takeaways instead of restating metric labels.

Progression knowledge:
- Double progression means the app normally adds reps at the current working load until work sets reach the top of the rep range, then raises load when a suitable heavier weight is available.
- After a double-progression load increase, lower reps or lower total volume can be expected; do not call that a regression if the session met the expected sets or clearly advanced load as planned.
- Auto-regulation uses the same double-progression baseline, then adjusts later work sets during the session from rep performance or recorded auto RIR on non-last work sets.
- For auto-regulation, around 2 RIR or reps inside the target range usually means keep the load, clearly below the minimum rep target means the load was likely too high and later sets may drop, and clearly above the maximum rep target or higher RIR means later sets may rise.
- Treat auto-regulated load changes as intended when the set data supports them; do not flatten them into inconsistency or simple volume drift.
- Progression state PROGRESS/RETRY/DELOAD/FAILED and comparisons vs expected or previous describe the app's progression decision; expected sets are the session target, and previous successful baseline is the success baseline.
- For double-progression or auto-regulated exercises, judge success against expected sets and progression comparisons before raw total volume.

Respond in markdown using these sections:
## What stood out
## Exercise trend

Requirements:
- Use as many bullets as needed for grounded, decision-useful details.
- Do not omit grounded, decision-useful details just to satisfy brevity, but merge related signals when one concise bullet can cover them accurately.
- Keep each bullet short, focused, and non-redundant.
- Do not repeat the same fact in multiple sections; if a section would only repeat an earlier point, skip that bullet.
- start every bullet with "- "
- no introduction or conclusion outside the required sections
- include HR when it changes or supports the interpretation, but do not let HR override clearer lifting evidence
- omit obvious filler
- do not force a negative point if the exercise was broadly solid

Before finalizing, silently verify:
- every claim is supported by the supplied evidence
- no bullet says something improved if the numeric value is lower
- mixed signals across latest session, baseline, and trend are stated explicitly when present
- double progression and auto-regulation are interpreted as progression systems, not as generic static targets
- the wording is natural and user-friendly
"""

internal val EXERCISE_INSIGHTS_SYSTEM_PROMPT = listOf(
    EXERCISE_INSIGHTS_SYSTEM_PROMPT_BASE.trimIndent(),
    FINAL_RESPONSE_NUMERIC_POLICY.trimIndent()
).joinToString("\n\n")

sealed class WorkoutInsightsPromptResult {
    data class Success(
        val title: String,
        val prompt: String,
        val systemPrompt: String,
        val toolContext: WorkoutInsightsToolContext? = null,
        val chartAnalysisContext: String? = null,
        val chartTimelineToolContext: WorkoutInsightsChartTimelineContext? = null,
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
                prompt = buildExerciseToolCallingPrompt(exercise.name),
                systemPrompt = buildToolEnabledSystemPrompt(EXERCISE_INSIGHTS_SYSTEM_PROMPT),
                toolContext = WorkoutInsightsToolContext.Exercise(
                    title = "${exercise.name} insights",
                    exerciseName = exercise.name,
                    markdown = markdownResult.markdown
                )
            )
        }
    }
}

suspend fun buildWorkoutSessionInsightsPrompt(
    workoutHistoryId: UUID,
    workoutHistoryDao: WorkoutHistoryDao,
    workoutRecordDao: WorkoutRecordDao,
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
            val workoutHistory = workoutHistoryDao.getWorkoutHistoryById(workoutHistoryId)
                ?: return WorkoutInsightsPromptResult.Failure("Workout session not found")
            val workoutRecord = workoutRecordDao.getWorkoutRecordByWorkoutHistoryId(workoutHistoryId)
            val workout = workoutStore.workouts.find { it.id == workoutHistory.workoutId }
            val sessionStatus = resolveWorkoutSessionStatus(workoutHistory, workoutRecord)
            val sessionStatusLine = "${buildWorkoutSessionStatusLine(sessionStatus)}\n"
            val sessionStatusSummary = describeWorkoutSessionStatusForPrompt(sessionStatus)
            val workoutType = workout?.type
            val workoutCategoryLine = workoutType
                ?.let(::buildWorkoutCategoryContextLine)
                ?.let { "$it\n" }
                .orEmpty()
            val workoutCategoryGuidance = workoutType
                ?.let(::buildWorkoutCategoryPromptGuidance)
                ?.let { "$it\n" }
                .orEmpty()
            val workoutLabel = buildWorkoutInsightLabel(
                workoutName = workout?.name,
                workoutCategoryLine = workoutCategoryLine
            )

            WorkoutInsightsPromptResult.Success(
                title = "Workout session insights",
                prompt = buildWorkoutSessionToolCallingPrompt(
                    workoutLabel = workoutLabel,
                    sessionStatusSummary = sessionStatusSummary
                ),
                systemPrompt = buildToolEnabledSystemPrompt(WORKOUT_INSIGHTS_SYSTEM_PROMPT),
                toolContext = WorkoutInsightsToolContext.WorkoutSession(
                    title = "Workout session insights",
                    workoutLabel = workoutLabel,
                    markdown = buildString {
                        append(sessionStatusLine)
                        if (workoutCategoryGuidance.isNotBlank()) {
                            append(workoutCategoryGuidance.trim())
                            append("\n\n")
                        }
                        append(workoutCategoryLine)
                        append(markdownResult.markdown)
                    }
                )
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
            "Focus on the latest completed session first, then use recent history only where it changes interpretation.",
            "Compare executed performance against expected work and the previous baseline, then explain any relevant trend.",
            "Include every grounded, decision-useful detail needed to explain whether the latest session beat, matched, or lagged plan, previous, baseline, or trend.",
            "Stay concise by combining related signals and avoiding repeated facts across sections.",
            "Interpret DOUBLE_PROGRESSION and AUTO_REGULATION as progression systems, not static load and volume targets.",
            "Use TAKEAWAY lines as authoritative user-facing comparison facts, and do not contradict them.",
            "When a TAKEAWAY says lower reps or volume are expected after a successful load increase, do not recommend reducing load just to match previous volume.",
            "If the latest session met plan but still lagged previous, baseline, or recent trend, say that explicitly.",
            "If load improved but reps, sets, or volume worsened, state that tradeoff clearly and account for planned double progression or auto-regulated adjustments when the evidence supports it.",
            "Use exact numbers for reasoning only; in final markdown, describe metric relationships qualitatively instead of writing kg, reps, set counts, bpm, percentages, duration, or volume values.",
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
        )?.trim().takeIf { it?.isNotBlank() == true }
    ).joinToString("\n")

    normalizePromptLayout(
        listOfNotNull(
            "Analyze this completed workout session and explain it in plain coaching language.",
            "Focus first on what mattered most in the latest session, then use plan, previous, best, and recent exercise context only where it changes the interpretation.",
            "Compare each exercise against plan, previous, and best-to-date performance.",
            "Include every grounded, decision-useful training detail instead of suppressing details for brevity.",
            "Stay concise by grouping exercises with the same takeaway and avoiding repeated facts across sections.",
            "For lifting-dominant sessions, interpret HR as supporting context and do not let it override clearer load, rep, set, and progression evidence.",
            "If current top load is higher than previous, mention it even when total volume is lower.",
            "If plan was met but performance still lagged previous or recent trend, say that clearly.",
            "If current volume is lower than previous, account for planned double-progression load jumps or auto-regulated load changes before calling it below previous.",
            "If Exec, Prev, Best, or Expected numbers disagree with status labels, trust the numbers.",
            "Interpret DOUBLE_PROGRESSION and AUTO_REGULATION as progression systems, not static load and volume targets.",
            "Use TAKEAWAY lines as authoritative user-facing comparison facts, and do not contradict them.",
            "Do not say an exercise reached the top or bottom of a rep range unless a TAKEAWAY line says that directly.",
            "When a TAKEAWAY says lower reps or volume are expected after a successful load increase, do not recommend reducing load just to match previous volume.",
            "Do not flatten mixed exercise results into overall progress when exercises diverge.",
            "Do not repeat internal labels; translate them into normal language.",
            "Use exact numbers for reasoning only; in final markdown, describe metric relationships qualitatively instead of writing kg, reps, set counts, bpm, percentages, duration, or volume values.",
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
        val recentSessions = addExerciseHistoryTakeaways(
            sessions.takeLast(sessionsToKeep).mapNotNull(::compactExerciseSessionBlock)
        )
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
        .let(::addExerciseHistoryTakeaways)
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

private fun addExerciseHistoryTakeaways(
    compactedSessions: List<String>,
): List<String> {
    if (compactedSessions.size < 2) return compactedSessions
    return compactedSessions.mapIndexed { index, session ->
        val previousSession = compactedSessions.getOrNull(index - 1)
        val takeawayLine = previousSession?.let { previous ->
            buildExerciseHistorySessionTakeawayLine(
                currentSession = session,
                previousSession = previous
            )
        }
        if (takeawayLine == null) {
            session
        } else {
            appendExerciseHistoryTakeawayLine(session, takeawayLine)
        }
    }
}

private fun appendExerciseHistoryTakeawayLine(
    session: String,
    takeawayLine: String,
): String {
    val lines = session.lines()
    val progressionIndex = lines.indexOfFirst { it.startsWith("PROG ") }
    if (progressionIndex < 0) {
        return buildString {
            append(session)
            append('\n')
            append(takeawayLine)
        }
    }
    return buildString {
        lines.forEachIndexed { index, line ->
            append(line)
            append('\n')
            if (index == progressionIndex) {
                append(takeawayLine)
                append('\n')
            }
        }
    }.trimEnd()
}

private fun buildExerciseHistorySessionTakeawayLine(
    currentSession: String,
    previousSession: String,
): String? {
    val currentProgression = parseExerciseHistoryProgressionLine(currentSession) ?: return null
    val previousProgression = parseExerciseHistoryProgressionLine(previousSession) ?: return null
    val currentEntries = currentProgression.executedEntries
    val previousEntries = previousProgression.executedEntries
    if (currentEntries.isEmpty() || previousEntries.isEmpty()) return null

    val loadStatus = compareDoubleValues(
        currentEntries.maxOf { it.load },
        previousEntries.maxOf { it.load }
    )
    val repStatus = compareIntValues(
        currentEntries.sumOf { it.setCount * it.reps },
        previousEntries.sumOf { it.setCount * it.reps }
    )
    val volumeStatus = compareNullableDoubleValues(
        currentProgression.executedVolumeKg,
        previousProgression.executedVolumeKg
    )

    val previousPhrase = when {
        loadStatus == "above" &&
            repStatus == "below" &&
            volumeStatus == "below" &&
            (currentProgression.planStatus == "above" || currentProgression.planStatus == "matched") ->
            "successful load increase; lower reps and volume are expected after the jump"
        loadStatus == "above" && repStatus == "below" && volumeStatus == "below" ->
            "heavier than the previous session, but with fewer reps and lower volume"
        loadStatus == "above" && (repStatus == "above" || volumeStatus == "above") ->
            "heavier than the previous session with more total work"
        loadStatus == "above" ->
            "heavier than the previous session"
        loadStatus == "matched" && repStatus == "above" && volumeStatus == "above" ->
            "same load as the previous session, with more reps and volume"
        loadStatus == "matched" && repStatus == "above" ->
            "same load as the previous session, with more reps"
        loadStatus == "matched" && volumeStatus == "above" ->
            "same load as the previous session, with more volume"
        loadStatus == "matched" && repStatus == "below" && volumeStatus == "below" ->
            "same load as the previous session, but with fewer reps and lower volume"
        loadStatus == "matched" && volumeStatus == "matched" ->
            "matched the previous session"
        loadStatus == "below" && (repStatus == "above" || volumeStatus == "above") ->
            "lighter than the previous session, but with more total work"
        loadStatus == "below" ->
            "lighter than the previous session"
        volumeStatus == "above" ->
            "more total work than the previous session"
        volumeStatus == "below" ->
            "less total work than the previous session"
        volumeStatus == "matched" ->
            "matched the previous session"
        else -> null
    }

    val planPhrase = currentProgression.planStatus?.let(::planStatusPhrase)
    val baselinePhrase = when (currentProgression.baselineStatus) {
        "above" -> "above the previous successful baseline"
        "matched" -> "matched the previous successful baseline"
        "below" -> "below the previous successful baseline"
        else -> null
    }
    val phrases = listOfNotNull(previousPhrase, planPhrase, baselinePhrase).distinct()
    if (phrases.isEmpty()) return null
    return "TAKEAWAY ${phrases.joinToString("; ")}."
}

private data class ExerciseHistoryProgressionData(
    val executedEntries: List<PromptSetSummaryEntry>,
    val executedVolumeKg: Double?,
    val planStatus: String?,
    val baselineStatus: String?,
)

private fun parseExerciseHistoryProgressionLine(
    session: String,
): ExerciseHistoryProgressionData? {
    val progressionLine = session.lineSequence()
        .firstOrNull { it.startsWith("PROG ") }
        ?: return null
    val payload = progressionLine.removePrefix("PROG ")
    val executedEntries = extractPromptSetSummaryEntriesFromPayload(
        extractStructuredPayloadValue(payload, "Executed")
    )
    return ExerciseHistoryProgressionData(
        executedEntries = executedEntries,
        executedVolumeKg = parseExerciseHistoryExecutedVolumeKg(payload),
        planStatus = (
            extractStructuredPayloadValue(payload, "Vs target")
                ?: extractStructuredPayloadValue(payload, "Vs expected")
            )?.toSignalStatus(),
        baselineStatus = extractStructuredPayloadValue(payload, "Vs success baseline")?.toSignalStatus(),
    )
}

private fun extractStructuredPayloadValue(
    payload: String,
    label: String,
): String? {
    val prefix = "$label:"
    return payload
        .split('|')
        .firstNotNullOfOrNull { part ->
            val trimmed = part.trim()
            if (!trimmed.startsWith(prefix, ignoreCase = true)) {
                null
            } else {
                trimmed.removePrefix(prefix).trim().takeIf { it.isNotBlank() }
            }
        }
}

private fun extractPromptSetSummaryEntriesFromPayload(
    payload: String?,
): List<PromptSetSummaryEntry> {
    return payload
        ?.split(';')
        ?.map { it.trim() }
        ?.mapNotNull(::parsePromptSetSummaryEntry)
        .orEmpty()
}

private fun parseExerciseHistoryExecutedVolumeKg(
    payload: String,
): Double? {
    val execValue = Regex("""\bVolume:\s*.*?\bExec\s+([^|]+)""", RegexOption.IGNORE_CASE)
        .find(payload)
        ?.groupValues
        ?.getOrNull(1)
        ?.trim()
        ?: return null
    return parseVolumeMetricKg(execValue)
}

private fun String.toSignalStatus(): String {
    return when (trim().lowercase()) {
        "equal", "met" -> "matched"
        else -> trim().lowercase()
    }
}

private fun compareDoubleValues(
    current: Double,
    previous: Double,
): String {
    return when {
        abs(current - previous) < 0.0001 -> "matched"
        current > previous -> "above"
        else -> "below"
    }
}

private fun compareNullableDoubleValues(
    current: Double?,
    previous: Double?,
): String? {
    if (current == null || previous == null) return null
    return compareDoubleValues(current, previous)
}

private fun compareIntValues(
    current: Int,
    previous: Int,
): String {
    return when {
        current == previous -> "matched"
        current > previous -> "above"
        else -> "below"
    }
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

private data class CompactSetSummaryEntry(
    val loadDescription: String,
    val reps: Int,
    val setCount: Int,
    val autoRegulationRir: String?,
)

private data class PromptSetSummaryEntry(
    val setCount: Int,
    val load: Double,
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
    return "$prefix ${renderCompactSetSummaryForPrompt(compactRepeatedEntryList(value))}"
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

private fun renderCompactSetSummaryForPrompt(
    compactedValue: String,
): String {
    val entries = compactedValue
        .split(',')
        .map { it.trim() }
        .filter { it.isNotBlank() }
    if (entries.isEmpty()) return compactedValue.trim()

    val parsedEntries = entries.map { entry ->
        parseCompactSetSummaryEntry(entry) ?: return compactedValue.trim()
    }

    return parsedEntries.joinToString("; ") { entry ->
        buildString {
            append(entry.setCount)
            append(if (entry.setCount == 1) " set" else " sets")
            append(" at ")
            append(entry.loadDescription)
            append(" for ")
            append(entry.reps)
            append(if (entry.reps == 1) " rep" else " reps")
            entry.autoRegulationRir?.let { rir ->
                append(" with auto RIR ")
                append(rir)
            }
        }
    }
}

private fun parseCompactSetSummaryEntry(
    entry: String,
): CompactSetSummaryEntry? {
    val match = Regex(
        """^(body weight \+\s*[0-9.]+\s*kg|[0-9.]+\s*kg)\s*x\s*(\d+)(?:\s*\(auto RIR\s*([0-9.]+)\))?(?:\s*\((\d+)\s+sets?\))?$""",
        RegexOption.IGNORE_CASE
    ).matchEntire(entry.trim()) ?: return null

    return CompactSetSummaryEntry(
        loadDescription = match.groupValues[1].replace(Regex("""\s+"""), " "),
        reps = match.groupValues[2].toIntOrNull() ?: return null,
        autoRegulationRir = match.groupValues[3].takeIf { it.isNotBlank() },
        setCount = match.groupValues[4].takeIf { it.isNotBlank() }?.toIntOrNull() ?: 1,
    )
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
        .replace(Regex("""Range:\s*(\d{4,6})(?:\s*bpm|\bbpm\b)""")) { match ->
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
        .split(',', ';')
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
    parsePromptSetSummaryEntryLoads(entry)?.let { return it }

    val load = parseSetSummaryLoad(entry) ?: return emptyList()
    val count = Regex("""\((\d+)\s+sets\)""", RegexOption.IGNORE_CASE)
        .find(entry)
        ?.groupValues
        ?.getOrNull(1)
        ?.toIntOrNull()
        ?: 1
    return List(count) { load }
}

private fun parsePromptSetSummaryEntryLoads(
    entry: String,
): List<Double>? {
    val match = Regex(
        """^(\d+)\s+sets?\s+at\s+(?:body weight \+\s*)?([0-9.]+)\s*kg\s+for\s+\d+\s+reps?(?:\s+with\s+auto\s+RIR\s+[0-9.]+)?$""",
        RegexOption.IGNORE_CASE
    ).matchEntire(entry.trim()) ?: return null
    val count = match.groupValues[1].toIntOrNull() ?: return null
    val load = match.groupValues[2].toDoubleOrNull() ?: return null
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
    buildWorkoutExerciseTakeawayLine(section)?.let { takeawayLine ->
        append('\n')
        append(takeawayLine)
    }
}.trim().takeWithinBudget(MAX_SECTION_CHAR_BUDGET)

private fun buildWorkoutExerciseTakeawayLine(
    section: CompactWorkoutSectionData,
): String? {
    val executedLines = section.subsections.firstOrNull { it.title == "Executed" }?.lines.orEmpty()
    val previousLines = section.subsections.firstOrNull { it.title == "Previous Session" }?.lines.orEmpty()
    val signalLines = section.subsections.firstOrNull { it.title == "Coaching Signals" }?.lines.orEmpty()

    val planPhrase = signalStatus(signalLines, "- Vs target:")
        ?.let(::planStatusPhrase)
    val previousPhrase = buildPreviousSessionTakeawayPhrase(
        signalLines = signalLines,
        executedLines = executedLines,
        previousLines = previousLines,
        planStatus = signalStatus(signalLines, "- Vs target:")
    )
    val bestPhrase = signalStatus(signalLines, "- Vs best:")
        ?.let(::bestStatusPhrase)

    val phrases = listOfNotNull(previousPhrase, planPhrase, bestPhrase)
        .distinct()
    if (phrases.isEmpty()) return null

    return "TAKEAWAY ${phrases.joinToString("; ")}."
}

private fun buildPreviousSessionTakeawayPhrase(
    signalLines: List<String>,
    executedLines: List<String>,
    previousLines: List<String>,
    planStatus: String?,
): String? {
    if (previousLines.any { it.equals("- No previous session", ignoreCase = true) }) {
        return "no previous completed session to compare against"
    }

    val volumeStatus = signalStatus(signalLines, "- Vs prev:")
    val topLoadStatus = signalStatus(signalLines, "- Top load vs prev:")
    val loadProfileStatus = signalStatus(signalLines, "- Load profile vs prev:")
    val repStatus = deriveTotalRepComparisonStatus(
        currentEntries = extractPromptSetSummaryEntries(executedLines),
        previousEntries = extractPromptSetSummaryEntries(previousLines)
    )
    val effectiveLoadStatus = topLoadStatus ?: loadProfileStatus

    return when {
        effectiveLoadStatus == "above" &&
            repStatus == "below" &&
            volumeStatus == "below" &&
            (planStatus == "above" || planStatus == "matched") ->
            "successful load increase; lower reps and volume are expected after the jump"
        effectiveLoadStatus == "above" && repStatus == "below" && volumeStatus == "below" ->
            "heavier than the previous session, but with fewer reps and lower volume"
        effectiveLoadStatus == "above" && repStatus == "below" ->
            "heavier than the previous session, but with fewer total reps"
        effectiveLoadStatus == "above" && volumeStatus == "below" ->
            "heavier than the previous session, but with lower volume"
        effectiveLoadStatus == "above" && (repStatus == "above" || volumeStatus == "above") ->
            "heavier than the previous session with more total work"
        effectiveLoadStatus == "above" ->
            "heavier than the previous session"
        effectiveLoadStatus == "matched" && repStatus == "above" && volumeStatus == "above" ->
            "same load as the previous session, with more reps and volume"
        effectiveLoadStatus == "matched" && repStatus == "above" ->
            "same load as the previous session, with more reps"
        effectiveLoadStatus == "matched" && volumeStatus == "above" ->
            "same load as the previous session, with more volume"
        effectiveLoadStatus == "matched" && repStatus == "below" && volumeStatus == "below" ->
            "same load as the previous session, but with fewer reps and lower volume"
        effectiveLoadStatus == "matched" && repStatus == "below" ->
            "same load as the previous session, but with fewer reps"
        effectiveLoadStatus == "matched" && volumeStatus == "below" ->
            "same load as the previous session, but with lower volume"
        effectiveLoadStatus == "matched" && volumeStatus == "matched" ->
            "matched the previous session"
        effectiveLoadStatus == "below" && (repStatus == "above" || volumeStatus == "above") ->
            "lighter than the previous session, but with more total work"
        effectiveLoadStatus == "below" ->
            "lighter than the previous session"
        volumeStatus == "above" ->
            "more total work than the previous session"
        volumeStatus == "below" ->
            "less total work than the previous session"
        volumeStatus == "matched" ->
            "matched the previous session"
        else -> null
    }
}

private fun signalStatus(
    signalLines: List<String>,
    prefix: String,
): String? {
    return signalLines.firstOrNull { it.startsWith(prefix, ignoreCase = true) }
        ?.substringAfter(':')
        ?.substringBefore('(')
        ?.trim()
        ?.lowercase()
        ?.let { status ->
            when (status) {
                "equal" -> "matched"
                "met" -> "matched"
                else -> status
            }
        }
        ?.takeIf { it.isNotBlank() }
}

private fun planStatusPhrase(
    status: String,
): String? {
    return when (status) {
        "above" -> "beat the plan"
        "matched" -> "met the plan"
        "below" -> "fell short of the plan"
        "mixed" -> "had mixed results against the plan"
        else -> null
    }
}

private fun bestStatusPhrase(
    status: String,
): String? {
    return when (status) {
        "above" -> "set a new best"
        "matched" -> "matched the best so far"
        "below" -> "below the best so far"
        else -> null
    }
}

private fun deriveTotalRepComparisonStatus(
    currentEntries: List<PromptSetSummaryEntry>,
    previousEntries: List<PromptSetSummaryEntry>,
): String? {
    if (currentEntries.isEmpty() || previousEntries.isEmpty()) return null
    val currentReps = currentEntries.sumOf { it.setCount * it.reps }
    val previousReps = previousEntries.sumOf { it.setCount * it.reps }
    return when {
        currentReps == previousReps -> "matched"
        currentReps > previousReps -> "above"
        else -> "below"
    }
}

private fun extractPromptSetSummaryEntries(
    lines: List<String>,
): List<PromptSetSummaryEntry> {
    val setsPayload = extractCompactValue(lines, "- Sets") ?: return emptyList()
    return setsPayload
        .split(';')
        .map { it.trim() }
        .mapNotNull(::parsePromptSetSummaryEntry)
}

private fun parsePromptSetSummaryEntry(
    entry: String,
): PromptSetSummaryEntry? {
    val match = Regex(
        """^(\d+)\s+sets?\s+at\s+(?:body weight \+\s*)?([0-9.]+)\s*kg\s+for\s+(\d+)\s+reps?(?:\s+with\s+auto\s+RIR\s+[0-9.]+)?$""",
        RegexOption.IGNORE_CASE
    ).matchEntire(entry.trim()) ?: return null
    return PromptSetSummaryEntry(
        setCount = match.groupValues[1].toIntOrNull() ?: return null,
        load = match.groupValues[2].toDoubleOrNull() ?: return null,
        reps = match.groupValues[3].toIntOrNull() ?: return null,
    )
}

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

private fun buildWorkoutSessionStatusLine(
    status: WorkoutSessionStatus,
): String = when (status) {
    WorkoutSessionStatus.COMPLETED -> "Session status: Completed normally"
    WorkoutSessionStatus.IN_PROGRESS_ON_PHONE -> "Session status: Still in progress on phone"
    WorkoutSessionStatus.IN_PROGRESS_ON_WEAR -> "Session status: Still in progress on wear device"
    WorkoutSessionStatus.STOPPED_ON_WEAR -> "Session status: Stopped on wear device before completion"
    WorkoutSessionStatus.STALE_ON_WEAR -> "Session status: Wear session became stale before completion"
}

private fun describeWorkoutSessionStatusForPrompt(
    status: WorkoutSessionStatus,
): String = when (status) {
    WorkoutSessionStatus.COMPLETED -> "completed normally"
    WorkoutSessionStatus.IN_PROGRESS_ON_PHONE -> "still in progress on phone"
    WorkoutSessionStatus.IN_PROGRESS_ON_WEAR -> "still in progress on wear device"
    WorkoutSessionStatus.STOPPED_ON_WEAR -> "stopped on wear device before completion"
    WorkoutSessionStatus.STALE_ON_WEAR -> "became stale on wear before completion"
}

private fun buildWorkoutInsightLabel(
    workoutName: String?,
    workoutCategoryLine: String,
): String {
    val baseLabel = workoutName?.trim().takeUnless { it.isNullOrBlank() } ?: "Workout session"
    val categoryLabel = workoutCategoryLine.trim()
    return if (categoryLabel.isBlank()) {
        baseLabel
    } else {
        "$baseLabel ($categoryLabel)"
    }
}

private data class ChartTimelineSegment(
    val label: String,
    val startSeconds: Int,
    val endSeconds: Int,
)

private data class ChartTimelineStep(
    val label: String,
    val startSeconds: Int,
    val endSeconds: Int,
)

internal fun buildWorkoutSessionChartTimelineToolContext(
    workoutHistory: com.gabstra.myworkoutassistant.shared.WorkoutHistory,
    workout: Workout,
    setHistories: List<com.gabstra.myworkoutassistant.shared.SetHistory>,
    restHistories: List<com.gabstra.myworkoutassistant.shared.RestHistory>,
): WorkoutInsightsChartTimelineContext? {
    val segments = buildWorkoutSessionChartTimelineSegments(
        workoutHistory = workoutHistory,
        workout = workout,
        setHistories = setHistories,
        restHistories = restHistories,
    ) ?: return null
    return WorkoutInsightsChartTimelineContext(
        durationSeconds = workoutHistory.duration,
        segments = segments.map {
            WorkoutInsightsChartTimelineSegment(
                startSeconds = it.startSeconds,
                endSeconds = it.endSeconds,
                label = it.label,
            )
        },
    )
}

private fun buildWorkoutSessionChartTimelineSegments(
    workoutHistory: com.gabstra.myworkoutassistant.shared.WorkoutHistory,
    workout: Workout,
    setHistories: List<com.gabstra.myworkoutassistant.shared.SetHistory>,
    restHistories: List<com.gabstra.myworkoutassistant.shared.RestHistory>,
): List<ChartTimelineSegment>? {
    val exerciseLabels = buildWorkoutExerciseLabels(workout)
    val mergedTimeline = mergeSessionTimeline(setHistories, restHistories)
    val steps = mutableListOf<ChartTimelineStep>()
    val segments = mutableListOf<ChartTimelineSegment>()

    fun addStep(label: String, startSeconds: Int, endSeconds: Int) {
        val normalizedLabel = label.trim().takeIf { it.isNotBlank() } ?: return
        val normalizedStart = startSeconds.coerceAtLeast(0)
        val normalizedEnd = endSeconds.coerceAtMost(workoutHistory.duration)
        if (normalizedEnd <= normalizedStart) return

        val previous = steps.lastOrNull()
        if (previous != null && previous.label == normalizedLabel && previous.endSeconds >= normalizedStart) {
            steps[steps.lastIndex] = previous.copy(endSeconds = maxOf(previous.endSeconds, normalizedEnd))
        } else {
            steps += ChartTimelineStep(
                label = normalizedLabel,
                startSeconds = normalizedStart,
                endSeconds = normalizedEnd
            )
        }
    }

    for (item in mergedTimeline) {
        when (item) {
            is SessionTimelineItem.SetStep -> {
                val start = secondsFromWorkoutStart(workoutHistory.startTime, item.history.startTime) ?: continue
                val end = secondsFromWorkoutStart(workoutHistory.startTime, item.history.endTime)
                    ?: (start + inferSetDurationSeconds(item.history))
                addStep(
                    label = exerciseLabels[item.history.exerciseId].orEmpty().ifBlank { "Unnamed exercise block" },
                    startSeconds = start,
                    endSeconds = end
                )
            }
            is SessionTimelineItem.RestStep -> {
                val start = secondsFromWorkoutStart(workoutHistory.startTime, item.history.startTime) ?: continue
                val end = secondsFromWorkoutStart(workoutHistory.startTime, item.history.endTime)
                    ?: (start + inferRestDurationSeconds(item.history))
                addStep(
                    label = buildRestTimelineLabel(
                        restHistory = item.history,
                        exerciseLabels = exerciseLabels,
                        existingSteps = steps
                    ),
                    startSeconds = start,
                    endSeconds = end
                )
            }
        }
    }

    val firstStep = steps.firstOrNull()
    if (firstStep != null && firstStep.startSeconds >= 120) {
        segments.add(
            0,
            ChartTimelineSegment(
                label = "Lead-in before ${firstStep.label}",
                startSeconds = 0,
                endSeconds = firstStep.startSeconds
            )
        )
    }

    segments += steps.map { step ->
        ChartTimelineSegment(
            label = step.label,
            startSeconds = step.startSeconds,
            endSeconds = step.endSeconds
        )
    }

    val lastStep = steps.lastOrNull()
    if (lastStep != null && workoutHistory.duration - lastStep.endSeconds >= 120) {
        segments += ChartTimelineSegment(
            label = "Wrap-up after ${lastStep.label}",
            startSeconds = lastStep.endSeconds,
            endSeconds = workoutHistory.duration
        )
    }

    return segments.takeIf { it.isNotEmpty() }
}

private fun buildWorkoutExerciseLabels(
    workout: Workout,
): Map<UUID, String> = buildMap {
    workout.workoutComponents.forEach { component ->
        when (component) {
            is Exercise -> put(component.id, component.name)
            is Superset -> component.exercises.forEach { exercise -> put(exercise.id, exercise.name) }
            is Rest -> Unit
        }
    }
}

private fun buildRestTimelineLabel(
    restHistory: com.gabstra.myworkoutassistant.shared.RestHistory,
    exerciseLabels: Map<UUID, String>,
    existingSteps: List<ChartTimelineStep>,
): String {
    val restExerciseLabel = restHistory.exerciseId
        ?.let(exerciseLabels::get)
        ?.trim()
        .orEmpty()
        .ifBlank { null }
    if (restExerciseLabel != null) {
        return "Rest after $restExerciseLabel"
    }

    val previousExerciseLabel = existingSteps
        .lastOrNull()
        ?.label
        ?.removePrefix("Lead-in before ")
        ?.removePrefix("Wrap-up after ")
        ?.trim()
        ?.takeIf { it.isNotBlank() }

    return if (previousExerciseLabel != null) {
        "Transition after $previousExerciseLabel"
    } else {
        "Session transition"
    }
}

private fun secondsFromWorkoutStart(
    workoutStart: LocalDateTime,
    eventTime: LocalDateTime?,
): Int? {
    eventTime ?: return null
    return Duration.between(workoutStart, eventTime).seconds.toInt().coerceAtLeast(0)
}

private fun inferSetDurationSeconds(
    setHistory: com.gabstra.myworkoutassistant.shared.SetHistory,
): Int = when (val setData = setHistory.setData) {
    is com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData ->
        ((setData.endTimer - setData.startTimer) / 1000).coerceAtLeast(30)
    is com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData ->
        (setData.endTimer / 1000).coerceAtLeast(30)
    else -> 45
}

private fun inferRestDurationSeconds(
    restHistory: com.gabstra.myworkoutassistant.shared.RestHistory,
): Int = when (val setData = restHistory.setData) {
    is com.gabstra.myworkoutassistant.shared.setdata.RestSetData ->
        (setData.endTimer / 1000).coerceAtLeast(15)
    else -> 30
}

private fun formatChartTimelineTimestamp(
    totalSeconds: Int,
): String {
    val safeSeconds = totalSeconds.coerceAtLeast(0)
    val hours = safeSeconds / 3600
    val minutes = (safeSeconds % 3600) / 60
    val seconds = safeSeconds % 60
    return if (hours > 0) {
        "%d:%02d:%02d".format(hours, minutes, seconds)
    } else {
        "%02d:%02d".format(minutes, seconds)
    }
}

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
    val rangeMatch =
        Regex("""(?i)(\bRange:\s*)(\d{4,6})(\s*bpm\b|\bbpm\b)""").find(line) ?: return line
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
