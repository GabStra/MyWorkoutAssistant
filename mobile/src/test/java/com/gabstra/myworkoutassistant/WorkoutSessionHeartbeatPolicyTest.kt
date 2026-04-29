package com.gabstra.myworkoutassistant

import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutRecord
import com.gabstra.myworkoutassistant.shared.datalayer.WorkoutSessionHeartbeat
import com.gabstra.myworkoutassistant.shared.datalayer.WorkoutSessionHeartbeatRejectReason
import com.gabstra.myworkoutassistant.shared.datalayer.decideWorkoutSessionHeartbeatApply
import com.gabstra.myworkoutassistant.shared.workout.model.SessionOwnerDevice
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID

class WorkoutSessionHeartbeatPolicyTest {

    private val workoutId = UUID.randomUUID()
    private val workoutHistoryId = UUID.randomUUID()
    private val exerciseId = UUID.randomUUID()
    private val now = LocalDateTime.of(2026, 4, 28, 12, 0)

    private fun heartbeat(revision: UInt = 3u): WorkoutSessionHeartbeat =
        WorkoutSessionHeartbeat(
            workoutId = workoutId,
            workoutHistoryId = workoutHistoryId,
            exerciseId = exerciseId,
            setIndex = 1u,
            sessionState = "Set",
            activeSessionRevision = revision,
            sentAtEpochMs = 1_777_376_000_000L
        )

    private fun history(
        id: UUID = workoutHistoryId,
        workoutId: UUID = this.workoutId,
        isDone: Boolean = false
    ): WorkoutHistory = WorkoutHistory(
        id = id,
        workoutId = workoutId,
        date = LocalDate.of(2026, 4, 28),
        time = LocalTime.of(12, 0),
        startTime = now.minusMinutes(10),
        duration = 0,
        heartBeatRecords = emptyList(),
        isDone = isDone,
        hasBeenSentToHealth = false,
        globalId = UUID.randomUUID()
    )

    private fun record(
        workoutId: UUID = this.workoutId,
        workoutHistoryId: UUID = this.workoutHistoryId,
        ownerDevice: SessionOwnerDevice = SessionOwnerDevice.WEAR,
        revision: UInt = 2u
    ): WorkoutRecord = WorkoutRecord(
        id = UUID.randomUUID(),
        workoutId = workoutId,
        workoutHistoryId = workoutHistoryId,
        setIndex = 0u,
        exerciseId = UUID.randomUUID(),
        ownerDevice = ownerDevice.name,
        lastActiveSyncAt = now.minusMinutes(2),
        activeSessionRevision = revision,
        lastKnownSessionState = "Set"
    )

    @Test
    fun `updates matching unfinished Wear record`() {
        val decision = decideWorkoutSessionHeartbeatApply(
            heartbeat = heartbeat(),
            existingRecord = record(),
            existingHistory = history()
        )

        assertTrue(decision.shouldApply)
    }

    @Test
    fun `ignores completed histories`() {
        val decision = decideWorkoutSessionHeartbeatApply(
            heartbeat = heartbeat(),
            existingRecord = record(),
            existingHistory = history(isDone = true)
        )

        assertEquals(WorkoutSessionHeartbeatRejectReason.COMPLETED_HISTORY, decision.rejectReason)
    }

    @Test
    fun `ignores missing history`() {
        val decision = decideWorkoutSessionHeartbeatApply(
            heartbeat = heartbeat(),
            existingRecord = record(),
            existingHistory = null
        )

        assertEquals(WorkoutSessionHeartbeatRejectReason.MISSING_HISTORY, decision.rejectReason)
    }

    @Test
    fun `rejects older revision`() {
        val decision = decideWorkoutSessionHeartbeatApply(
            heartbeat = heartbeat(revision = 1u),
            existingRecord = record(revision = 2u),
            existingHistory = history()
        )

        assertEquals(WorkoutSessionHeartbeatRejectReason.OLDER_REVISION, decision.rejectReason)
    }
}
