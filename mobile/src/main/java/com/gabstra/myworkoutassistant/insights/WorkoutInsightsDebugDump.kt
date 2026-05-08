package com.gabstra.myworkoutassistant.insights

import android.content.Context
import android.util.Base64
import android.util.Log
import com.gabstra.myworkoutassistant.writeJsonToDownloadsFolder
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import java.util.UUID

private const val INSIGHTS_DEBUG_DUMP_SCHEMA_VERSION = 1
private const val INSIGHTS_DEBUG_DUMP_LOG_TAG = "WorkoutInsights"

class WorkoutInsightsDebugDumpRecorder(
    private val context: Context,
    private val fileName: String,
    mode: WorkoutInsightsMode,
    request: WorkoutInsightsRequest,
) {
    private val startedAtEpochMs = System.currentTimeMillis()
    private val sessionId = UUID.randomUUID().toString()
    private val blocks = mutableListOf<JSONObject>()
    private val transportRequests = mutableListOf<JSONObject>()
    private val statusUpdates = mutableListOf<JSONObject>()
    private var saved = false
    private val root = JSONObject().apply {
        put("schema_version", INSIGHTS_DEBUG_DUMP_SCHEMA_VERSION)
        put("session_id", sessionId)
        put("started_at_epoch_ms", startedAtEpochMs)
        put("mode", mode.name)
        put(
            "request",
            JSONObject().apply {
                put("title", request.title)
                put("tool_context_type", request.toolContext?.javaClass?.simpleName ?: JSONObject.NULL)
                put("has_chart_image", request.imagePngBytes != null)
                put("has_chart_timeline_tool_context", request.chartTimelineToolContext != null)
                put("uses_transport_tool_calling", request.useTransportToolCalling)
                put("history_chat_system_includes_data", request.historyChatSystemIncludesData)
                put("custom_instructions", request.customInstructions)
            }
        )
    }

    @Synchronized
    fun recordTransportRequest(
        transportRequest: WorkoutInsightsTransportRequest,
        backendMetadata: Map<String, Any?> = emptyMap(),
    ) {
        transportRequests += JSONObject().apply {
            put("recorded_at_epoch_ms", System.currentTimeMillis())
            put("request_log_label", transportRequest.requestLogLabel)
            put("response_log_label", transportRequest.responseLogLabel)
            put("max_output_tokens", transportRequest.maxOutputTokens ?: JSONObject.NULL)
            put("conversation_messages", transportRequest.conversationMessages.toJsonArray())
            put("tool_context_type", transportRequest.toolContext?.javaClass?.simpleName ?: JSONObject.NULL)
            put("chart_timeline_tool_context", transportRequest.chartTimelineToolContext.toJson())
            put("image_png_base64", transportRequest.imagePngBytes?.toBase64() ?: JSONObject.NULL)
            put("backend_metadata", backendMetadata.toJsonObject())
        }
    }

    @Synchronized
    fun recordBlock(
        label: String,
        body: String,
    ) {
        blocks += JSONObject().apply {
            put("index", blocks.size + 1)
            put("recorded_at_epoch_ms", System.currentTimeMillis())
            put("label", label)
            put("body", body)
        }
    }

    @Synchronized
    fun recordStatus(
        phase: WorkoutInsightsPhase,
        statusText: String,
    ) {
        statusUpdates += JSONObject().apply {
            put("recorded_at_epoch_ms", System.currentTimeMillis())
            put("phase", phase.name)
            put("status_text", statusText)
        }
    }

    @Synchronized
    fun finishSuccess(finalDisplayedText: String) {
        finish(
            outcome = "success",
            finalDisplayedText = finalDisplayedText,
            errorMessage = null,
        )
    }

    @Synchronized
    fun finishFailure(
        errorMessage: String,
        lastDisplayedText: String,
    ) {
        finish(
            outcome = "failure",
            finalDisplayedText = lastDisplayedText,
            errorMessage = errorMessage,
        )
    }

    @Synchronized
    fun finishCancelled(lastDisplayedText: String) {
        finish(
            outcome = "cancelled",
            finalDisplayedText = lastDisplayedText,
            errorMessage = null,
        )
    }

    @Synchronized
    private fun finish(
        outcome: String,
        finalDisplayedText: String,
        errorMessage: String?,
    ) {
        if (saved) return
        root.put("finished_at_epoch_ms", System.currentTimeMillis())
        root.put("transport_requests", JSONArray(transportRequests))
        root.put("status_updates", JSONArray(statusUpdates))
        root.put("blocks", JSONArray(blocks))
        root.put(
            "result",
            JSONObject().apply {
                put("outcome", outcome)
                put("final_displayed_text", finalDisplayedText)
                put("error_message", errorMessage ?: JSONObject.NULL)
            }
        )
        saved = true
        writeJsonToDownloadsFolder(context, fileName, root.toString(2))
        Log.d(INSIGHTS_DEBUG_DUMP_LOG_TAG, "insights_debug_dump_saved file=$fileName outcome=$outcome")
    }
}

internal fun createWorkoutInsightsDebugDumpRecorder(
    context: Context,
    mode: WorkoutInsightsMode,
    request: WorkoutInsightsRequest,
): WorkoutInsightsDebugDumpRecorder {
    return WorkoutInsightsDebugDumpRecorder(
        context = context.applicationContext,
        fileName = buildWorkoutInsightsDebugDumpFileName(
            timestamp = Date(),
            mode = mode,
            title = request.title,
        ),
        mode = mode,
        request = request,
    )
}

internal fun buildWorkoutInsightsDebugDumpFileName(
    timestamp: Date,
    mode: WorkoutInsightsMode,
    title: String,
): String {
    val formattedTimestamp =
        SimpleDateFormat("yyyy-MM-dd_HH-mm-ss", Locale.US).apply {
            timeZone = TimeZone.getTimeZone("UTC")
        }.format(timestamp)
    val slug = title
        .lowercase(Locale.US)
        .replace(Regex("[^a-z0-9]+"), "_")
        .trim('_')
        .take(48)
        .ifBlank { "untitled" }
    return "workout_insights_debug_${formattedTimestamp}_${mode.name.lowercase(Locale.US)}_$slug.json"
}

private fun List<HistoryChatMessage>.toJsonArray(): JSONArray {
    return JSONArray(
        map { message ->
            JSONObject().apply {
                put("role", message.role.name)
                put("content", message.content)
            }
        }
    )
}

private fun WorkoutInsightsChartTimelineContext?.toJson(): Any {
    if (this == null) return JSONObject.NULL
    return JSONObject().apply {
        put("duration_seconds", durationSeconds)
        put(
            "segments",
            JSONArray(
                segments.map { segment ->
                    JSONObject().apply {
                        put("start_seconds", segment.startSeconds)
                        put("end_seconds", segment.endSeconds)
                        put("label", segment.label)
                    }
                }
            )
        )
    }
}

private fun ByteArray.toBase64(): String = Base64.encodeToString(this, Base64.NO_WRAP)

private fun Map<String, Any?>.toJsonObject(): JSONObject {
    return JSONObject().apply {
        entries.forEach { (key, value) ->
            put(key, value ?: JSONObject.NULL)
        }
    }
}
