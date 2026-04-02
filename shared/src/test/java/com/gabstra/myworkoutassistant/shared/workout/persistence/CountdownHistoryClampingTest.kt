package com.gabstra.myworkoutassistant.shared.workout.persistence

import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.workout.history.clampElapsedSecondsToPlanned
import java.time.LocalDateTime
import org.junit.Assert.assertEquals
import org.junit.Test

class CountdownHistoryClampingTest {

    @Test
    fun `resolvePersistedHistoryEndTime derives rest end time from timer progress`() {
        val startTime = LocalDateTime.of(2026, 4, 2, 10, 0, 0)
        val recordedEndTime = startTime.plusSeconds(61)

        val resolved = resolvePersistedHistoryEndTime(
            setData = RestSetData(startTimer = 75, endTimer = 20),
            startTime = startTime,
            recordedEndTime = recordedEndTime,
        )

        assertEquals(startTime.plusSeconds(55), resolved)
    }

    @Test
    fun `resolvePersistedHistoryEndTime derives timed duration end time from timer progress`() {
        val startTime = LocalDateTime.of(2026, 4, 2, 10, 0, 0)
        val recordedEndTime = startTime.plusNanos(60_500_000L)

        val resolved = resolvePersistedHistoryEndTime(
            setData = TimedDurationSetData(
                startTimer = 60_000,
                endTimer = 12_500,
                autoStart = false,
                autoStop = true,
            ),
            startTime = startTime,
            recordedEndTime = recordedEndTime,
        )

        assertEquals(startTime.plusNanos(47_500_000_000L), resolved)
    }

    @Test
    fun `resolvePersistedHistoryEndTime keeps wall clock end time for non countdown sets`() {
        val startTime = LocalDateTime.of(2026, 4, 2, 10, 0, 0)
        val recordedEndTime = startTime.plusSeconds(42)

        val resolved = resolvePersistedHistoryEndTime(
            setData = WeightSetData(actualReps = 8, actualWeight = 80.0, volume = 640.0),
            startTime = startTime,
            recordedEndTime = recordedEndTime,
        )

        assertEquals(recordedEndTime, resolved)
    }

    @Test
    fun `clampElapsedSecondsToPlanned caps elapsed display to planned duration`() {
        assertEquals(60, clampElapsedSecondsToPlanned(elapsedSeconds = 61, plannedSeconds = 60))
        assertEquals(42, clampElapsedSecondsToPlanned(elapsedSeconds = 42, plannedSeconds = 60))
    }
}
