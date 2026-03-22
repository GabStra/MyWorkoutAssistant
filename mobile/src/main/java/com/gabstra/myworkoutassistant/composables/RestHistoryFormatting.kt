package com.gabstra.myworkoutassistant.composables

import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import java.time.Duration

internal fun formatHistoricalRestValue(history: SetHistory): String {
    val setData = history.setData as? RestSetData ?: return ""
    val elapsedSeconds = history.startTime
        ?.let { startTime ->
            history.endTime?.let { endTime ->
                Duration.between(startTime, endTime).seconds
                    .takeIf { it >= 0L }
                    ?.coerceAtMost(Int.MAX_VALUE.toLong())
                    ?.toInt()
            }
        }
        ?: (setData.startTimer - setData.endTimer).coerceAtLeast(0)
    return "REST ${formatTime(elapsedSeconds)}"
}
