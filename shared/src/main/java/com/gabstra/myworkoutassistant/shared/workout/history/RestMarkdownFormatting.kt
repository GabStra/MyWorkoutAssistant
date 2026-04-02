package com.gabstra.myworkoutassistant.shared.workout.history

import com.gabstra.myworkoutassistant.shared.RestHistory
import com.gabstra.myworkoutassistant.shared.RestHistoryScope
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData

/**
 * Formats rest duration for Markdown export, aligned with [formatRestIntervalForDisplay] in mobile
 * [com.gabstra.myworkoutassistant.composables.RestHistoryFormatting] (elapsed vs planned).
 */
fun formatRestLineForMarkdown(restHistory: RestHistory): String {
    val sd = restHistory.setData as? RestSetData ?: return "Rest: (unknown)"
    val plannedSec = sd.startTimer.coerceAtLeast(0)
    val elapsedSec = clampElapsedSecondsToPlanned(
        elapsedSeconds = elapsedSecondsFromHistoryBounds(restHistory.startTime, restHistory.endTime),
        plannedSeconds = plannedSec,
    )

    val scopeSuffix = when (restHistory.scope) {
        RestHistoryScope.INTRA_EXERCISE -> " [intra-exercise]"
        RestHistoryScope.BETWEEN_WORKOUT_COMPONENTS -> " [between components]"
    }

    val body = when {
        elapsedSec != null -> buildString {
            append("Rest: ${formatDurationSecondsForMarkdown(elapsedSec)} elapsed")
            if (plannedSec > 0 && plannedSec != elapsedSec) {
                append(" (${formatDurationSecondsForMarkdown(plannedSec)} planned)")
            }
        }
        else -> "Rest: ${formatDurationSecondsForMarkdown(plannedSec)} planned"
    }
    return body + scopeSuffix
}

fun formatDurationSecondsForMarkdown(seconds: Int): String {
    val s = seconds.coerceAtLeast(0)
    val hours = s / 3600
    val minutes = (s % 3600) / 60
    val remainingSeconds = s % 60
    return if (hours > 0) {
        String.format("%d:%02d:%02d", hours, minutes, remainingSeconds)
    } else {
        String.format("%d:%02d", minutes, remainingSeconds)
    }
}
