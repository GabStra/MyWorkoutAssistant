package com.gabstra.myworkoutassistant.shared.workout.model

import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutRecord
import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID

class WorkoutSessionStatusTest {

    private val now = LocalDateTime.of(2026, 3, 20, 10, 0)

    private fun workoutHistory(isDone: Boolean): WorkoutHistory {
        val startTime = now.minusMinutes(30)
        return WorkoutHistory(
            id = UUID.randomUUID(),
            workoutId = UUID.randomUUID(),
            date = LocalDate.of(2026, 3, 20),
            time = LocalTime.of(9, 30),
            startTime = startTime,
            duration = 0,
            heartBeatRecords = emptyList(),
            isDone = isDone,
            hasBeenSentToHealth = false,
            globalId = UUID.randomUUID(),
        )
    }

    private fun workoutRecord(
        historyId: UUID,
        ownerDevice: SessionOwnerDevice,
        lastActiveSyncAt: LocalDateTime? = now
    ): WorkoutRecord = WorkoutRecord(
        id = UUID.randomUUID(),
        workoutId = UUID.randomUUID(),
        workoutHistoryId = historyId,
        setIndex = 0u,
        exerciseId = UUID.randomUUID(),
        ownerDevice = ownerDevice.name,
        lastActiveSyncAt = lastActiveSyncAt,
    )

    @Test
    fun `completed history resolves to completed`() {
        val history = workoutHistory(isDone = true)

        assertEquals(
            WorkoutSessionStatus.COMPLETED,
            resolveWorkoutSessionStatus(history, null, now = now)
        )
    }

    @Test
    fun `fresh wear record resolves to in progress on wear`() {
        val history = workoutHistory(isDone = false)
        val record = workoutRecord(history.id, SessionOwnerDevice.WEAR, now.minusSeconds(10))

        assertEquals(
            WorkoutSessionStatus.IN_PROGRESS_ON_WEAR,
            resolveWorkoutSessionStatus(history, record, now = now)
        )
    }

    @Test
    fun `stale wear record resolves to stale on wear`() {
        val history = workoutHistory(isDone = false)
        val record = workoutRecord(history.id, SessionOwnerDevice.WEAR, now.minusMinutes(5))

        assertEquals(
            WorkoutSessionStatus.STALE_ON_WEAR,
            resolveWorkoutSessionStatus(history, record, now = now)
        )
    }

    @Test
    fun `missing active record resolves to interrupted`() {
        val history = workoutHistory(isDone = false)

        assertEquals(
            WorkoutSessionStatus.INTERRUPTED,
            resolveWorkoutSessionStatus(history, null, now = now)
        )
    }
}
