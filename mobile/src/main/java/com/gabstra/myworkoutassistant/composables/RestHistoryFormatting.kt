package com.gabstra.myworkoutassistant.composables

import android.content.res.Resources
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.shared.RestHistory
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.workout.history.clampElapsedSecondsToPlanned
import com.gabstra.myworkoutassistant.shared.workout.history.elapsedSecondsFromHistoryBounds
import java.time.LocalDateTime

/**
 * Locale-independent rest values ready for UI formatting.
 *
 * [elapsedSeconds] is null when persisted timestamps cannot produce an elapsed duration; in that
 * case only the planned duration is known.
 */
data class RestHistoryDisplay(
    val plannedSeconds: Int,
    val elapsedSeconds: Int?,
)

fun SetHistory.restHistoryDisplay(): RestHistoryDisplay? {
    val restSetData = setData as? RestSetData ?: return null
    return restHistoryDisplay(restSetData, startTime, endTime)
}

fun RestHistory.restHistoryDisplay(): RestHistoryDisplay? {
    val restSetData = setData as? RestSetData ?: return null
    return restHistoryDisplay(restSetData, startTime, endTime)
}

/**
 * [SetHistory] rows whose [SetHistory.setData] is [RestSetData] (e.g. when rest was stored on
 * `set_history`). Prefer [formatRestHistoryDisplayLine] for rows from [rest_history]. Pass
 * [Resources] from the UI boundary to resolve the active locale; omitting them keeps the
 * locale-independent fallback used by non-composable table builders.
 */
fun formatHistoricalRestValue(
    setHistory: SetHistory,
    resources: Resources? = null,
): String {
    return setHistory.restHistoryDisplay()?.toDisplayText(resources) ?: restFallbackText(resources)
}

/** Any persisted [RestHistory] row (intra-exercise or between components). */
fun formatRestHistoryDisplayLine(
    history: RestHistory,
    resources: Resources? = null,
): String {
    return history.restHistoryDisplay()?.toDisplayText(resources) ?: restFallbackText(resources)
}

private fun restHistoryDisplay(
    restSetData: RestSetData,
    startTime: LocalDateTime?,
    endTime: LocalDateTime?,
): RestHistoryDisplay {
    val plannedSec = restSetData.startTimer.coerceAtLeast(0)
    val elapsedSec = clampElapsedSecondsToPlanned(
        elapsedSeconds = elapsedSecondsFromHistoryBounds(startTime, endTime),
        plannedSeconds = plannedSec,
    )
    return RestHistoryDisplay(
        plannedSeconds = plannedSec,
        elapsedSeconds = elapsedSec,
    )
}

private fun restFallbackText(resources: Resources?): String {
    return resources?.getString(R.string.loc_status_rest_fallback) ?: "Rest"
}

private fun RestHistoryDisplay.toDisplayText(resources: Resources?): String {
    if (resources == null) {
        val elapsed = elapsedSeconds ?: return "REST ${formatTime(plannedSeconds)}"
        return when {
            plannedSeconds > 0 && plannedSeconds != elapsed ->
                "REST ${formatTime(elapsed)} elapsed (${formatTime(plannedSeconds)} planned)"
            else -> "REST ${formatTime(elapsed)} elapsed"
        }
    }

    val restLabel = resources.getString(R.string.loc_status_rest_label)
    val elapsed = elapsedSeconds ?: return resources.getString(
        R.string.loc_status_rest_duration,
        restLabel,
        formatTime(plannedSeconds),
    )
    return when {
        plannedSeconds > 0 && plannedSeconds != elapsed -> resources.getString(
            R.string.loc_status_rest_elapsed_planned,
            restLabel,
            formatTime(elapsed),
            formatTime(plannedSeconds),
        )
        else -> resources.getString(
            R.string.loc_status_rest_elapsed,
            restLabel,
            formatTime(elapsed),
        )
    }
}
