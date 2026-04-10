package com.gabstra.myworkoutassistant.insights

import android.util.Log
import com.google.ai.edge.litertlm.OpenApiTool
import com.google.ai.edge.litertlm.ToolProvider
import com.google.ai.edge.litertlm.tool
import com.openai.core.JsonValue
import com.openai.models.FunctionDefinition
import com.openai.models.FunctionParameters
import org.json.JSONArray
import org.json.JSONObject

internal const val MAX_INSIGHTS_TOOL_ROUNDS = 4
private const val MAX_TOOL_TEXT_FIELD_CHARS = 12_000
private const val MAX_TOOL_SESSION_SNIPPET_CHARS = 1_400
private const val DEFAULT_WORKOUT_OVERVIEW_CHARS = MAX_TOOL_TEXT_FIELD_CHARS
private const val DEFAULT_WORKOUT_SECTION_CHARS = MAX_TOOL_TEXT_FIELD_CHARS
private const val DEFAULT_FULL_WORKOUT_SESSION_CHARS = MAX_TOOL_TEXT_FIELD_CHARS
private const val INSIGHT_LOG_PREVIEW_CHARS = 240
private const val INSIGHT_LOG_CHUNK_CHARS = 3_000
private val WORKOUT_SESSION_SECTION_DELIMITER = Regex("(?m)^(?:EXERCISE|SUPERSET) ")

data class WorkoutInsightsChartTimelineSegment(
    val startSeconds: Int,
    val endSeconds: Int,
    val label: String,
)

data class WorkoutInsightsChartTimelineContext(
    val durationSeconds: Int,
    val segments: List<WorkoutInsightsChartTimelineSegment>,
)

internal class WorkoutInsightsChartTimelineToolExecutor(
    private val timeline: WorkoutInsightsChartTimelineContext,
) {
    private val spec = WorkoutInsightsToolSpec(
        name = "get_session_timeline_for_time_range",
        description = """
            Returns workout blocks (exercises, rests, lead-in, wrap-up) overlapping an elapsed-time window.
            Times are seconds from workout start (inclusive window endpoints).
            Request windows that need session block labels for a visible heart-rate pattern; chart-only analysis remains valid with zero calls.
        """.trimIndent().replace("\n", " "),
        parametersSchema = mapOf(
            "type" to "object",
            "properties" to mapOf(
                "start_seconds" to mapOf(
                    "type" to "integer",
                    "description" to "Window start in seconds since workout start (inclusive)."
                ),
                "end_seconds" to mapOf(
                    "type" to "integer",
                    "description" to "Window end in seconds since workout start (inclusive)."
                ),
                "max_chars" to mapOf(
                    "type" to "integer",
                    "description" to "Maximum characters for the returned block list. Default: 1800."
                )
            ),
            "required" to listOf("start_seconds", "end_seconds")
        ),
        handler = { args ->
            buildChartTimelineRangeResult(
                timeline = timeline,
                startSecondsArg = args.intOrDefault("start_seconds", 0),
                endSecondsArg = args.intOrDefault("end_seconds", timeline.durationSeconds),
                maxChars = args.maxCharsOrDefault(1800),
            )
        }
    )

    fun liteRtTools(): List<ToolProvider> = listOf(tool(InsightsOpenApiTool(spec)))

    fun openAiFunctionDefinitions(): List<FunctionDefinition> = listOf(
        FunctionDefinition.builder()
            .name(spec.name)
            .description(spec.description)
            .parameters(
                requireNotNull(
                    JsonValue.from(spec.parametersSchema)
                        .convert(FunctionParameters::class.java)
                )
            )
            .strict(true)
            .build()
    )

    fun describeToolsForLog(): String = buildString {
        append("Tool: ")
        append(spec.name)
        append("\nDescription: ")
        append(spec.description)
        append("\nParameters:\n")
        append(renderForInsightLog(spec.parametersSchema))
    }

    fun executeToJsonString(
        name: String,
        arguments: Map<String, Any?>,
    ): String {
        if (name != spec.name) {
            return JSONObject(
                mapOf(
                    "ok" to false,
                    "error" to "Unknown tool: $name"
                )
            ).toString()
        }
        val result = runCatching { spec.handler(arguments) }
            .getOrElse { error ->
                mapOf(
                    "ok" to false,
                    "error" to (error.message ?: "Tool execution failed")
                )
            }
        return renderToolResult(result)
    }
}

internal fun buildChartTimelineRangeResult(
    timeline: WorkoutInsightsChartTimelineContext,
    startSecondsArg: Int,
    endSecondsArg: Int,
    maxChars: Int,
): Map<String, Any?> {
    val duration = timeline.durationSeconds.coerceAtLeast(0)
    var start = startSecondsArg.coerceIn(0, duration)
    var end = endSecondsArg.coerceIn(0, duration)
    if (start > end) {
        val tmp = start
        start = end
        end = tmp
    }
    val overlapping = timeline.segments.filter { seg ->
        seg.startSeconds <= end && seg.endSeconds >= start
    }
    val lines = overlapping.map { seg ->
        "- ${formatChartTimelineSeconds(seg.startSeconds)}-${formatChartTimelineSeconds(seg.endSeconds)} ${seg.label}"
    }
    val text = lines.joinToString("\n").takeWithinBudget(maxChars.coerceIn(200, 4000))
    return mapOf(
        "ok" to true,
        "sessionDurationSeconds" to duration,
        "requestedStartSeconds" to start,
        "requestedEndSeconds" to end,
        "blockCount" to overlapping.size,
        "blocks" to text,
    )
}

private fun formatChartTimelineSeconds(
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

sealed class WorkoutInsightsToolContext {
    abstract val title: String
    abstract val markdown: String

    data class Exercise(
        override val title: String,
        val exerciseName: String,
        override val markdown: String,
    ) : WorkoutInsightsToolContext()

    data class WorkoutSession(
        override val title: String,
        val workoutLabel: String,
        override val markdown: String,
    ) : WorkoutInsightsToolContext()
}

internal data class WorkoutInsightsToolSpec(
    val name: String,
    val description: String,
    val parametersSchema: Map<String, Any?>,
    val handler: (Map<String, Any?>) -> Any,
)

internal class WorkoutInsightsToolExecutor(
    private val toolContext: WorkoutInsightsToolContext,
) {
    private val specs: Map<String, WorkoutInsightsToolSpec> = buildSpecs(toolContext).associateBy { it.name }

    fun liteRtTools(): List<ToolProvider> = specs.values.map { spec ->
        tool(InsightsOpenApiTool(spec))
    }

    fun openAiFunctionDefinitions(): List<FunctionDefinition> = specs.values.map { spec ->
        FunctionDefinition.builder()
            .name(spec.name)
            .description(spec.description)
            .parameters(
                requireNotNull(
                    JsonValue.from(spec.parametersSchema)
                        .convert(FunctionParameters::class.java)
                )
            )
            .strict(true)
            .build()
    }

    fun describeToolsForLog(): String = specs.values.joinToString("\n\n") { spec ->
        buildString {
            append("Tool: ")
            append(spec.name)
            append("\nDescription: ")
            append(spec.description)
            append("\nParameters:\n")
            append(renderForInsightLog(spec.parametersSchema))
        }
    }

    fun executeToJsonString(
        name: String,
        arguments: Map<String, Any?>,
    ): String {
        val spec = specs[name] ?: return JSONObject(
            mapOf(
                "ok" to false,
                "error" to "Unknown tool: $name"
            )
        ).toString()

        val result = runCatching { spec.handler(arguments) }
            .getOrElse { error ->
                mapOf(
                    "ok" to false,
                    "error" to (error.message ?: "Tool execution failed")
                )
            }
        return renderToolResult(result)
    }

    private fun buildSpecs(
        toolContext: WorkoutInsightsToolContext,
    ): List<WorkoutInsightsToolSpec> {
        return when (toolContext) {
            is WorkoutInsightsToolContext.Exercise -> buildExerciseSpecs(toolContext)
            is WorkoutInsightsToolContext.WorkoutSession -> buildWorkoutSessionSpecs(toolContext)
        }
    }
}

internal fun buildToolEnabledSystemPrompt(
    basePrompt: String,
): String = """
${basePrompt.trim()}

Retrieval policy:
- You have tools for scoped workout-history retrieval and compression.
- Start with the smallest useful retrieval.
- Treat the first overview as scouting context, not final evidence, unless it already covers the needed exercises and comparisons explicitly.
- Prefer latest explicit metrics first, then recent trend context.
- Investigate further whenever the current evidence is mixed, truncated, generic, or missing exercise-level detail needed for Risks or Next session.
- If a workout has multiple main exercises, verify the relevant lagging or improving exercise with a narrower retrieval before concluding.
- Use summarization tools only when raw scoped context would be too verbose.
- Stop calling tools once you have enough evidence to answer confidently.
- Do not ask for data outside the available tools.

Final synthesis policy:
- Base the final answer only on retrieved tool outputs.
- If evidence is partial, say so plainly instead of overreaching.
- If a tool payload says `truncated: true` or the returned text ends with `...`, fetch narrower context before concluding.
- Do not write a workout-level risk or next-step recommendation from a generic overview alone when an exercise section is available.
""".trimIndent()

internal fun buildExerciseToolCallingPrompt(
    exerciseName: String,
): String = """
Task: produce focused training insights for $exerciseName.

Workflow:
1. Fetch the latest session or recent sessions first.
2. Fetch broader context only if the latest data is insufficient.
3. Summarize older history only when needed.
4. Stop tool use and write the final answer once you can explain latest performance, recent trend, and the clearest risk or next-step cue.
""".trimIndent()

internal fun buildWorkoutSessionToolCallingPrompt(
    workoutLabel: String,
    sessionStatusSummary: String,
): String = """
Task: analyze the workout session "$workoutLabel" and produce focused coaching insights.
Session status: $sessionStatusSummary.

Workflow:
1. Fetch the compact session overview first.
2. Treat that overview as a first pass only; if it is mixed, incomplete, truncated, generic, or missing one of the main exercises, fetch specific sections before concluding.
3. Use summary tools only when the remaining context is too large.
4. If the session was not completed normally, treat that as an important constraint on interpretation.
5. For lifting-dominant sessions, do not use modest session HR or 0% high-intensity exposure as the main risk by itself.
6. Before writing Risks or Next session, verify the clearest lagging or improving exercise with a narrower retrieval when available.
7. Stop tool use and write the final answer once you can explain what went well, what drifted, the main risk, and one clear next-session adjustment.
""".trimIndent()

private class InsightsOpenApiTool(
    private val spec: WorkoutInsightsToolSpec,
) : OpenApiTool {
    override fun getToolDescriptionJsonString(): String {
        return JSONObject(
            mapOf(
                "name" to spec.name,
                "description" to spec.description,
                "parameters" to spec.parametersSchema
            )
        ).toString()
    }

    override fun execute(
        paramsJsonString: String,
    ): String {
        val params = if (paramsJsonString.isBlank()) {
            emptyMap()
        } else {
            jsonObjectToMap(JSONObject(paramsJsonString))
        }
        val result = runCatching { spec.handler(params) }
            .getOrElse { error ->
                mapOf(
                    "ok" to false,
                    "error" to (error.message ?: "Tool execution failed")
                )
            }
        return JSONObject.wrap(result)?.toString()
            ?: JSONObject(mapOf("ok" to true, "result" to result.toString())).toString()
    }
}

private fun buildExerciseSpecs(
    toolContext: WorkoutInsightsToolContext.Exercise,
): List<WorkoutInsightsToolSpec> {
    val trimmedMarkdown = toolContext.markdown.trim()
    val blocks = splitMarkdownBlocks(trimmedMarkdown, Regex("(?m)^## S\\d+:"))
    val header = blocks.firstOrNull().orEmpty().trim()
    val sessions = blocks.drop(1).map { it.trim() }

    return listOf(
        WorkoutInsightsToolSpec(
            name = "get_context_overview",
            description = "Get the compact overview for the current insight target. Use this first when you need high-level context before deciding on narrower retrieval.",
            parametersSchema = maxCharsParametersSchema(defaultMaxChars = 1200),
            handler = { args ->
                mapOf(
                    "ok" to true,
                    "target" to toolContext.exerciseName,
                    "overview" to header.takeWithinBudget(args.maxCharsOrDefault(1200))
                )
            }
        ),
        WorkoutInsightsToolSpec(
            name = "get_latest_session",
            description = "Get the latest completed session details for the current exercise. Prefer this before broader history when diagnosing current performance.",
            parametersSchema = maxCharsParametersSchema(defaultMaxChars = MAX_TOOL_SESSION_SNIPPET_CHARS),
            handler = { args ->
                mapOf(
                    "ok" to true,
                    "target" to toolContext.exerciseName,
                    "latestSession" to sessions.lastOrNull()
                        ?.takeWithinBudget(args.maxCharsOrDefault(MAX_TOOL_SESSION_SNIPPET_CHARS))
                        .orEmpty()
                )
            }
        ),
        WorkoutInsightsToolSpec(
            name = "get_recent_sessions",
            description = "Get the most recent completed sessions for the current exercise. Use this when you need short-term trend context after checking the latest session.",
            parametersSchema = mapOf(
                "type" to "object",
                "properties" to mapOf(
                    "limit" to mapOf(
                        "type" to "integer",
                        "description" to "How many recent sessions to return. Default: 3."
                    ),
                    "max_chars" to mapOf(
                        "type" to "integer",
                        "description" to "Maximum number of characters in the returned payload. Default: 2200."
                    )
                )
            ),
            handler = { args ->
                val limit = args.intOrDefault("limit", 3).coerceIn(1, 6)
                val maxChars = args.maxCharsOrDefault(2200)
                val selected = sessions.takeLast(limit)
                mapOf(
                    "ok" to true,
                    "target" to toolContext.exerciseName,
                    "sessionCount" to selected.size,
                    "sessions" to selected.joinToString("\n\n").takeWithinBudget(maxChars)
                )
            }
        ),
        WorkoutInsightsToolSpec(
            name = "summarize_older_history",
            description = "Return a compact summary of older exercise history while keeping the newest sessions separate. Use only when recent sessions are not enough.",
            parametersSchema = mapOf(
                "type" to "object",
                "properties" to mapOf(
                    "keep_recent" to mapOf(
                        "type" to "integer",
                        "description" to "How many most recent sessions to exclude from the summary. Default: 2."
                    ),
                    "max_chars" to mapOf(
                        "type" to "integer",
                        "description" to "Maximum number of characters in the returned summary. Default: 1400."
                    )
                )
            ),
            handler = { args ->
                val keepRecent = args.intOrDefault("keep_recent", 2).coerceAtLeast(1)
                val maxChars = args.maxCharsOrDefault(1400)
                val olderSessions = sessions.dropLast(keepRecent)
                val summary = if (olderSessions.isEmpty()) {
                    "No older completed sessions remain after excluding the most recent $keepRecent."
                } else {
                    buildString {
                        append("Older completed sessions: ")
                        append(olderSessions.size)
                        append("\n\n")
                        append(olderSessions.joinToString("\n\n"))
                    }
                }
                mapOf(
                    "ok" to true,
                    "target" to toolContext.exerciseName,
                    "summary" to summary.takeWithinBudget(maxChars)
                )
            }
        ),
        WorkoutInsightsToolSpec(
            name = "get_full_compact_history",
            description = "Get the full compacted exercise history when a broader view is required and the smaller tools are still insufficient.",
            parametersSchema = maxCharsParametersSchema(defaultMaxChars = 3000),
            handler = { args ->
                mapOf(
                    "ok" to true,
                    "target" to toolContext.exerciseName,
                    "history" to compactExerciseHistoryMarkdown(
                        markdown = trimmedMarkdown,
                        markdownCharBudget = args.maxCharsOrDefault(3000)
                    )
                )
            }
        )
    )
}

private fun buildWorkoutSessionSpecs(
    toolContext: WorkoutInsightsToolContext.WorkoutSession,
): List<WorkoutInsightsToolSpec> {
    val compactMarkdown = compactWorkoutSessionMarkdown(toolContext.markdown, markdownCharBudget = 3200)
    val (topLevelOverview, sections) = splitWorkoutSessionOverviewAndSections(compactMarkdown)
    val overview = buildWorkoutSessionOverview(
        topLevelOverview = topLevelOverview,
        sectionBlocks = sections.values.toList()
    )

    return listOf(
        WorkoutInsightsToolSpec(
            name = "get_context_overview",
            description = "Get the compact overview for the current workout session. Use this first when you need the high-level session picture.",
            parametersSchema = maxCharsParametersSchema(defaultMaxChars = DEFAULT_WORKOUT_OVERVIEW_CHARS),
            handler = { args ->
                val maxChars = args.maxCharsOrDefault(DEFAULT_WORKOUT_OVERVIEW_CHARS)
                mapOf(
                    "ok" to true,
                    "target" to toolContext.workoutLabel,
                    "truncated" to (overview.length > maxChars),
                    "overview" to overview.takeWithinBudget(maxChars)
                )
            }
        ),
        WorkoutInsightsToolSpec(
            name = "get_full_compact_session",
            description = "Get the full compacted workout session context when the overview is not enough and you need broader detail.",
            parametersSchema = maxCharsParametersSchema(defaultMaxChars = DEFAULT_FULL_WORKOUT_SESSION_CHARS),
            handler = { args ->
                val maxChars = args.maxCharsOrDefault(DEFAULT_FULL_WORKOUT_SESSION_CHARS)
                mapOf(
                    "ok" to true,
                    "target" to toolContext.workoutLabel,
                    "truncated" to (compactMarkdown.length > maxChars),
                    "session" to compactMarkdown.takeWithinBudget(maxChars)
                )
            }
        ),
        WorkoutInsightsToolSpec(
            name = "get_session_section",
            description = "Get one named section from the compacted workout session context. Prefer this over the full session when you only need one exercise or subsection.",
            parametersSchema = mapOf(
                "type" to "object",
                "properties" to mapOf(
                    "section_title" to mapOf(
                        "type" to "string",
                        "description" to "The section title to fetch, such as an exercise name."
                    ),
                    "max_chars" to mapOf(
                        "type" to "integer",
                        "description" to "Maximum number of characters in the returned section. Default: $DEFAULT_WORKOUT_SECTION_CHARS."
                    )
                ),
                "required" to listOf("section_title")
            ),
            handler = { args ->
                val requested = args.stringValue("section_title").trim()
                val maxChars = args.maxCharsOrDefault(DEFAULT_WORKOUT_SECTION_CHARS)
                val match = sections.entries.firstOrNull { (title, _) ->
                    title.equals(requested, ignoreCase = true)
                }?.value ?: "No section found for \"$requested\"."
                mapOf(
                    "ok" to true,
                    "target" to toolContext.workoutLabel,
                    "sectionTitle" to requested,
                    "truncated" to (match.length > maxChars),
                    "section" to match.takeWithinBudget(maxChars)
                )
            }
        ),
        WorkoutInsightsToolSpec(
            name = "summarize_secondary_sections",
            description = "Return a compact summary of lower-priority workout sections when the primary sections are already enough to frame the answer.",
            parametersSchema = maxCharsParametersSchema(defaultMaxChars = 1400),
            handler = { args ->
                val maxChars = args.maxCharsOrDefault(1400)
                val secondary = sections.values.drop(2).joinToString("\n\n")
                mapOf(
                    "ok" to true,
                    "target" to toolContext.workoutLabel,
                    "summary" to if (secondary.isBlank()) {
                        "No secondary sections remain after the primary workout sections."
                    } else {
                        secondary.takeWithinBudget(maxChars)
                    }
                )
            }
        )
    )
}

internal fun splitWorkoutSessionOverviewAndSections(
    compactMarkdown: String,
): Pair<String, Map<String, String>> {
    val blocks = splitMarkdownBlocks(compactMarkdown.trim(), WORKOUT_SESSION_SECTION_DELIMITER)
    val topLevelOverview = blocks.firstOrNull().orEmpty().trim()
    val sections = blocks.drop(1).associateBy { block ->
        block.lineSequence()
            .firstOrNull()
            ?.removePrefix("EXERCISE ")
            ?.removePrefix("SUPERSET ")
            ?.trim()
            .orEmpty()
    }
    return topLevelOverview to sections
}

internal fun buildWorkoutSessionOverview(
    topLevelOverview: String,
    sectionBlocks: List<String>,
): String {
    val prioritizedHeaderLines = topLevelOverview
        .lineSequence()
        .map(String::trim)
        .filter { it.isNotBlank() }
        .filterNot { it.startsWith("EXERCISE ", ignoreCase = true) || it.startsWith("SUPERSET ", ignoreCase = true) }
        .toList()

    val sectionSummaryLines = sectionBlocks.mapNotNull(::buildWorkoutSectionOverviewLine)

    return buildString {
        append(
            prioritizedHeaderLines.joinToString("\n")
        )
        if (sectionSummaryLines.isNotEmpty()) {
            if (isNotEmpty()) {
                append("\n\n")
            }
            append(sectionSummaryLines.joinToString("\n"))
        }
    }.trim()
}

internal fun buildWorkoutSectionOverviewLine(
    sectionBlock: String,
): String? {
    val lines = sectionBlock
        .lineSequence()
        .map(String::trim)
        .filter { it.isNotBlank() }
        .toList()
    val heading = lines.firstOrNull() ?: return null
    val title = heading
        .removePrefix("EXERCISE ")
        .removePrefix("SUPERSET ")
        .trim()
        .takeIf { it.isNotBlank() }
        ?: return null
    val summaryParts = buildList {
        add("EXERCISE $title")
        lines.firstOrNull { it.startsWith("EXEC ") }?.let(::add)
        lines.firstOrNull { it.startsWith("PREV ") }?.let(::add)
        lines.firstOrNull { it.startsWith("SIGNALS ") }?.let(::add)
    }
    return summaryParts.joinToString(" | ").takeWithinBudget(320)
}

private fun maxCharsParametersSchema(
    defaultMaxChars: Int,
): Map<String, Any?> = mapOf(
    "type" to "object",
    "properties" to mapOf(
        "max_chars" to mapOf(
            "type" to "integer",
            "description" to "Maximum number of characters in the returned payload. Default: $defaultMaxChars."
        )
    )
)

private fun Map<String, Any?>.intOrDefault(
    key: String,
    default: Int,
): Int = when (val value = this[key]) {
    is Number -> value.toInt()
    is String -> value.toIntOrNull() ?: default
    else -> default
}

private fun Map<String, Any?>.maxCharsOrDefault(
    default: Int,
): Int = intOrDefault("max_chars", default).coerceIn(200, MAX_TOOL_TEXT_FIELD_CHARS)

private fun Map<String, Any?>.stringValue(
    key: String,
): String = when (val value = this[key]) {
    null -> ""
    is String -> value
    else -> value.toString()
}

private fun splitMarkdownBlocks(
    markdown: String,
    delimiter: Regex,
): List<String> {
    val matches = delimiter.findAll(markdown).toList()
    if (matches.isEmpty()) return listOf(markdown)

    val blocks = mutableListOf<String>()
    var cursor = 0
    for (match in matches) {
        val start = match.range.first
        if (start > cursor) {
            blocks += markdown.substring(cursor, start)
        }
        cursor = start
    }
    if (cursor < markdown.length) {
        blocks += markdown.substring(cursor)
    }
    return blocks.filter { it.isNotBlank() }
}

private fun String.takeWithinBudget(
    maxChars: Int,
): String {
    val normalized = trim()
    if (normalized.length <= maxChars) return normalized
    if (maxChars <= 3) return normalized.take(maxChars)
    return normalized.take(maxChars - 3).trimEnd() + "..."
}

internal fun jsonObjectToMap(
    jsonObject: JSONObject,
): Map<String, Any?> = buildMap {
    val keys = jsonObject.keys()
    while (keys.hasNext()) {
        val key = keys.next()
        put(key, jsonValueToAny(jsonObject.get(key)))
    }
}

private fun jsonArrayToList(
    jsonArray: JSONArray,
): List<Any?> = buildList {
    for (index in 0 until jsonArray.length()) {
        add(jsonValueToAny(jsonArray.get(index)))
    }
}

private fun jsonValueToAny(
    value: Any?,
): Any? = when (value) {
    JSONObject.NULL -> null
    is JSONObject -> jsonObjectToMap(value)
    is JSONArray -> jsonArrayToList(value)
    else -> value
}

internal fun renderForInsightLog(
    value: Any?,
): String = when (value) {
    null -> "null"
    is JSONObject -> value.toString(2)
    is JSONArray -> value.toString(2)
    is Map<*, *> -> JSONObject(value).toString(2)
    is List<*> -> JSONArray(value).toString(2)
    else -> value.toString()
}

private fun renderToolResult(
    result: Any,
): String {
    return when (val wrapped = JSONObject.wrap(result)) {
        is JSONObject -> wrapped
        is JSONArray -> JSONObject(mapOf("ok" to true, "result" to wrapped))
        else -> JSONObject(mapOf("ok" to true, "result" to wrapped))
    }.toString()
}

internal fun logWorkoutInsightsBlock(
    logTag: String,
    label: String,
    body: String,
) {
    if (Log.isLoggable(logTag, Log.VERBOSE)) {
        logWorkoutInsightsBlockChunks(Log.VERBOSE, logTag, label, body)
        return
    }

    if (INSIGHTS_FULL_DEBUG_LOGS_ENABLED) {
        logWorkoutInsightsBlockChunks(Log.DEBUG, logTag, label, body)
        return
    }

    Log.d(
        logTag,
        "$label chars=${body.length} lines=${body.lines().size} preview=${body.logPreview()}"
    )
}

private fun logWorkoutInsightsBlockChunks(
    priority: Int,
    logTag: String,
    label: String,
    body: String,
) {
    val chunkCount = ((body.length + INSIGHT_LOG_CHUNK_CHARS - 1) / INSIGHT_LOG_CHUNK_CHARS)
        .coerceAtLeast(1)
    Log.println(
        priority,
        logTag,
        "$label full_start chars=${body.length} lines=${body.lines().size} chunks=$chunkCount"
    )

    for (chunkIndex in 0 until chunkCount) {
        val startIndex = chunkIndex * INSIGHT_LOG_CHUNK_CHARS
        val endIndex = (startIndex + INSIGHT_LOG_CHUNK_CHARS).coerceAtMost(body.length)
        val chunk = body.substring(startIndex, endIndex)
        Log.println(
            priority,
            logTag,
            "${label}_part_${chunkIndex + 1}_of_$chunkCount\n$chunk"
        )
    }

    Log.println(priority, logTag, "$label full_end")
}

private fun String.logPreview(): String {
    return replace(Regex("\\s+"), " ")
        .trim()
        .takeWithinBudget(INSIGHT_LOG_PREVIEW_CHARS)
}

internal fun logConversationSummary(
    logTag: String,
    phase: String,
    turns: Int,
    toolNames: List<String>,
    exitReason: String,
    responseChars: Int,
) {
    val tools = if (toolNames.isEmpty()) "[]" else toolNames.joinToString(",", "[", "]")
    Log.d(logTag, "$phase turns=$turns tools=$tools exit=$exitReason chars=$responseChars")
}
