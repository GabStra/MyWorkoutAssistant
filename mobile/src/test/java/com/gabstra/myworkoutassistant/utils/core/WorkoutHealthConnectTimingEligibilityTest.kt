package com.gabstra.myworkoutassistant.utils.core

import androidx.health.connect.client.records.metadata.Metadata
import com.gabstra.myworkoutassistant.hasHealthConnectTiming
import com.gabstra.myworkoutassistant.toHealthConnectMetadata
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryOrigin
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.LocalTime
import java.util.UUID

class WorkoutHealthConnectTimingEligibilityTest {

    private fun history(
        startTimeKnown: Boolean = true,
        durationKnown: Boolean = true,
        durationSeconds: Int = 1800,
        origin: WorkoutHistoryOrigin = WorkoutHistoryOrigin.RECORDED,
    ): WorkoutHistory {
        val date = LocalDate.of(2026, 5, 20)
        val time = if (startTimeKnown) LocalTime.of(9, 0) else LocalTime.MIDNIGHT
        return WorkoutHistory(
            id = UUID.randomUUID(),
            workoutId = UUID.randomUUID(),
            date = date,
            time = time,
            startTime = date.atTime(time),
            duration = durationSeconds,
            heartBeatRecords = emptyList(),
            isDone = true,
            hasBeenSentToHealth = false,
            globalId = UUID.randomUUID(),
            origin = origin,
            startTimeKnown = startTimeKnown,
            durationKnown = durationKnown,
        )
    }

    @Test
    fun `recorded session with measured start and duration is eligible`() {
        val recordedHistory = history()
        assertTrue(recordedHistory.hasHealthConnectTiming())
        assertEquals(
            Metadata.RECORDING_METHOD_ACTIVELY_RECORDED,
            recordedHistory.toHealthConnectMetadata().recordingMethod,
        )
    }

    @Test
    fun `known user imported session is manually entered in Health Connect`() {
        val importedHistory = history(origin = WorkoutHistoryOrigin.USER_IMPORTED)

        assertTrue(importedHistory.hasHealthConnectTiming())
        assertEquals(
            Metadata.RECORDING_METHOD_MANUAL_ENTRY,
            importedHistory.toHealthConnectMetadata().recordingMethod,
        )
        assertEquals(
            importedHistory.id.toString(),
            importedHistory.toHealthConnectMetadata().clientRecordId,
        )
    }

    @Test
    fun `imported session with unknown start time is never eligible`() {
        assertFalse(
            history(
                startTimeKnown = false,
                durationKnown = true,
                origin = WorkoutHistoryOrigin.USER_IMPORTED,
            ).hasHealthConnectTiming()
        )
    }

    @Test
    fun `imported session with unknown duration is never eligible`() {
        assertFalse(
            history(
                durationKnown = false,
                durationSeconds = 0,
                origin = WorkoutHistoryOrigin.USER_IMPORTED,
            ).hasHealthConnectTiming()
        )
    }
}
