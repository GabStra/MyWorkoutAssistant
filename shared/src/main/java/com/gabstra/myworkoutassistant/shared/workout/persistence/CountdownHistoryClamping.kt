package com.gabstra.myworkoutassistant.shared.workout.persistence

import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import java.time.LocalDateTime

internal fun resolvePersistedHistoryEndTime(
    setData: SetData,
    startTime: LocalDateTime,
    recordedEndTime: LocalDateTime,
): LocalDateTime {
    return when (setData) {
        is RestSetData -> startTime.plusSeconds(restElapsedSeconds(setData).toLong())
        is TimedDurationSetData -> startTime.plusNanos(timedDurationElapsedMillis(setData).toLong() * 1_000_000L)
        else -> recordedEndTime
    }
}

private fun restElapsedSeconds(setData: RestSetData): Int {
    val plannedSeconds = setData.startTimer.coerceAtLeast(0)
    return (plannedSeconds - setData.endTimer).coerceIn(0, plannedSeconds)
}

private fun timedDurationElapsedMillis(setData: TimedDurationSetData): Int {
    val plannedMillis = setData.startTimer.coerceAtLeast(0)
    return (plannedMillis - setData.endTimer).coerceIn(0, plannedMillis)
}
