package com.gabstra.myworkoutassistant.shared.workout.model

import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutRecord
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID

class WorkoutRecordMergePolicyTest {

    private val baseStart = LocalDateTime.of(2026, 3, 24, 10, 0)

    private fun history(id: UUID = UUID.randomUUID(), version: UInt = 1u): WorkoutHistory = WorkoutHistory(
        id = id,
        workoutId = UUID.randomUUID(),
        date = LocalDate.of(2026, 3, 24),
        time = LocalTime.of(10, 0),
        startTime = baseStart,
        duration = 0,
        heartBeatRecords = emptyList(),
        isDone = false,
        hasBeenSentToHealth = false,
        globalId = UUID.randomUUID(),
        version = version
    )

    private fun record(
        workoutId: UUID,
        historyId: UUID,
        revision: UInt,
        setIndex: UInt = 0u,
        owner: SessionOwnerDevice = SessionOwnerDevice.PHONE
    ): WorkoutRecord = WorkoutRecord(
        id = UUID.randomUUID(),
        workoutId = workoutId,
        workoutHistoryId = historyId,
        setIndex = setIndex,
        exerciseId = UUID.randomUUID(),
        ownerDevice = owner.name,
        lastActiveSyncAt = baseStart,
        activeSessionRevision = revision
    )

    @Test
    fun `equal revision and version prefers incoming when history differs`() {
        val workoutId = UUID.randomUUID()
        val incomingHistory = history(version = 3u)
        val existingHistory = history(version = 3u)
        val incomingRecord = record(workoutId, incomingHistory.id, revision = 5u, owner = SessionOwnerDevice.WEAR)
        val existingRecord = record(workoutId, existingHistory.id, revision = 5u, owner = SessionOwnerDevice.PHONE)

        val decision = decideWorkoutRecordIngest(
            incomingHistory = incomingHistory,
            incomingRecord = incomingRecord,
            existingHistory = existingHistory,
            existingRecord = existingRecord
        )

        assertTrue(decision.shouldApplyIncoming)
        assertTrue(decision.shouldPruneExisting)
    }

    @Test
    fun `lower incoming revision is rejected`() {
        val workoutId = UUID.randomUUID()
        val sameHistory = history(version = 2u)
        val incomingRecord = record(workoutId, sameHistory.id, revision = 2u, owner = SessionOwnerDevice.WEAR)
        val existingRecord = record(workoutId, sameHistory.id, revision = 3u, owner = SessionOwnerDevice.PHONE)

        val decision = decideWorkoutRecordIngest(
            incomingHistory = sameHistory,
            incomingRecord = incomingRecord,
            existingHistory = sameHistory,
            existingRecord = existingRecord
        )

        assertFalse(decision.shouldApplyIncoming)
    }

    @Test
    fun `higher incoming history version is accepted at equal revision`() {
        val workoutId = UUID.randomUUID()
        val incomingHistory = history(version = 5u)
        val existingHistory = history(version = 4u)
        val incomingRecord = record(workoutId, incomingHistory.id, revision = 2u)
        val existingRecord = record(workoutId, existingHistory.id, revision = 2u)

        val decision = decideWorkoutRecordIngest(
            incomingHistory = incomingHistory,
            incomingRecord = incomingRecord,
            existingHistory = existingHistory,
            existingRecord = existingRecord
        )

        assertTrue(decision.shouldApplyIncoming)
        assertTrue(decision.shouldPruneExisting)
    }
}
