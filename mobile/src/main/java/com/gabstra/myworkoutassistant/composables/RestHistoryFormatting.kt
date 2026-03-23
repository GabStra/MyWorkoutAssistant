package com.gabstra.myworkoutassistant.composables

import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.shared.RestHistory
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.workout.history.elapsedSecondsFromHistoryBounds
import java.time.LocalDateTime

/**
 * [SetHistory] rows whose [SetHistory.setData] is [RestSetData] (e.g. when rest was stored on
 * `set_history`). Prefer [formatRestHistoryDisplayLine] for rows from [rest_history].
 */
fun formatHistoricalRestValue(setHistory: SetHistory): String {
    val sd = setHistory.setData as? RestSetData ?: return "Rest"
    return formatRestIntervalForDisplay(sd, setHistory.startTime, setHistory.endTime)
}

/** Any persisted [RestHistory] row (intra-exercise or between components). */
fun formatRestHistoryDisplayLine(history: RestHistory): String {
    val sd = history.setData as? RestSetData ?: return "Rest"
    return formatRestIntervalForDisplay(sd, history.startTime, history.endTime)
}

private fun formatRestIntervalForDisplay(
    restSetData: RestSetData,
    startTime: LocalDateTime?,
    endTime: LocalDateTime?,
): String {
    val plannedSec = restSetData.startTimer.coerceAtLeast(0)
    val elapsedSec = elapsedSecondsFromHistoryBounds(startTime, endTime)
    return when {
        elapsedSec != null -> buildString {
            append("REST ${formatTime(elapsedSec)} elapsed")
            if (plannedSec > 0 && plannedSec != elapsedSec) {
                append(" (${formatTime(plannedSec)} planned)")
            }
        }
        else -> "REST ${formatTime(plannedSec)}"
    }
}
