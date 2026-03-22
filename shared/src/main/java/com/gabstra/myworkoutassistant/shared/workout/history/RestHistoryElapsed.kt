package com.gabstra.myworkoutassistant.shared.workout.history

import java.time.Duration
import java.time.LocalDateTime

/**
 * Wall-clock rest duration in seconds from recorded bounds, or null if missing or invalid.
 */
fun elapsedSecondsFromHistoryBounds(startTime: LocalDateTime?, endTime: LocalDateTime?): Int? {
    if (startTime == null || endTime == null) return null
    val seconds = Duration.between(startTime, endTime).seconds
    return if (seconds >= 0L) seconds.toInt() else null
}
