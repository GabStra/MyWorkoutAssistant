package com.gabstra.myworkoutassistant.shared.workout.model

import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutRecord
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class WorkoutRecordBackupMergeTest {
    private val baseStart = LocalDateTime.of(2026, 4, 1, 10, 0)

    @Test
    fun mergeWorkoutRecordsForBackup_preservesNewerLocalWearRecordWhenIncomingIsStale() {
        val workoutId = UUID.randomUUID()
        val localHistory = history(id = UUID.randomUUID(), workoutId = workoutId, version = 4u)
        val incomingHistory = history(id = UUID.randomUUID(), workoutId = workoutId, version = 2u)
        val localRecord = record(
            workoutId = workoutId,
            historyId = localHistory.id,
            revision = 5u,
            owner = SessionOwnerDevice.WEAR
        )
        val incomingRecord = record(
            workoutId = workoutId,
            historyId = incomingHistory.id,
            revision = 3u,
            owner = SessionOwnerDevice.PHONE
        )

        val merged = mergeWorkoutRecordsForBackup(
            existingRecords = listOf(localRecord),
            existingHistoriesById = mapOf(localHistory.id to localHistory),
            incomingRecords = listOf(incomingRecord),
            incomingHistoriesById = mapOf(incomingHistory.id to incomingHistory)
        )

        assertEquals(listOf(localRecord.id), merged.map { it.id })
    }

    @Test
    fun mergeWorkoutRecordsForBackup_keepsLocalRecordWhenIncomingHasNoEntryForWorkout() {
        val workoutId = UUID.randomUUID()
        val localHistory = history(id = UUID.randomUUID(), workoutId = workoutId, version = 2u)
        val localRecord = record(
            workoutId = workoutId,
            historyId = localHistory.id,
            revision = 2u,
            owner = SessionOwnerDevice.WEAR
        )

        val merged = mergeWorkoutRecordsForBackup(
            existingRecords = listOf(localRecord),
            existingHistoriesById = mapOf(localHistory.id to localHistory),
            incomingRecords = emptyList(),
            incomingHistoriesById = emptyMap()
        )

        assertEquals(listOf(localRecord.id), merged.map { it.id })
    }

    @Test
    fun mergeWorkoutRecordsForBackup_appliesIncomingRecordWhenItWins() {
        val workoutId = UUID.randomUUID()
        val localHistory = history(id = UUID.randomUUID(), workoutId = workoutId, version = 1u)
        val incomingHistory = history(id = UUID.randomUUID(), workoutId = workoutId, version = 3u)
        val localRecord = record(
            workoutId = workoutId,
            historyId = localHistory.id,
            revision = 2u,
            owner = SessionOwnerDevice.WEAR
        )
        val incomingRecord = record(
            workoutId = workoutId,
            historyId = incomingHistory.id,
            revision = 4u,
            owner = SessionOwnerDevice.PHONE
        )

        val merged = mergeWorkoutRecordsForBackup(
            existingRecords = listOf(localRecord),
            existingHistoriesById = mapOf(localHistory.id to localHistory),
            incomingRecords = listOf(incomingRecord),
            incomingHistoriesById = mapOf(incomingHistory.id to incomingHistory)
        )

        assertEquals(listOf(incomingRecord.id), merged.map { it.id })
    }

    @Test
    fun mergeWorkoutRecordsForBackup_dropsRecordsWhoseHistoriesAreDoneOrMissing() {
        val workoutId = UUID.randomUUID()
        val completedHistory = history(
            id = UUID.randomUUID(),
            workoutId = workoutId,
            isDone = true
        )
        val completedRecord = record(
            workoutId = workoutId,
            historyId = completedHistory.id,
            revision = 1u
        )
        val missingHistoryRecord = record(
            workoutId = UUID.randomUUID(),
            historyId = UUID.randomUUID(),
            revision = 1u
        )

        val merged = mergeWorkoutRecordsForBackup(
            existingRecords = listOf(completedRecord, missingHistoryRecord),
            existingHistoriesById = mapOf(completedHistory.id to completedHistory),
            incomingRecords = emptyList(),
            incomingHistoriesById = emptyMap()
        )

        assertTrue(merged.isEmpty())
    }

    private fun history(
        id: UUID,
        workoutId: UUID,
        version: UInt = 1u,
        isDone: Boolean = false
    ): WorkoutHistory = WorkoutHistory(
        id = id,
        workoutId = workoutId,
        date = LocalDate.of(2026, 4, 1),
        time = LocalTime.of(10, 0),
        startTime = baseStart,
        duration = 0,
        heartBeatRecords = emptyList(),
        isDone = isDone,
        hasBeenSentToHealth = false,
        globalId = UUID.randomUUID(),
        version = version
    )

    private fun record(
        workoutId: UUID,
        historyId: UUID,
        revision: UInt,
        owner: SessionOwnerDevice = SessionOwnerDevice.PHONE
    ): WorkoutRecord = WorkoutRecord(
        id = UUID.randomUUID(),
        workoutId = workoutId,
        workoutHistoryId = historyId,
        setIndex = 0u,
        exerciseId = UUID.randomUUID(),
        ownerDevice = owner.name,
        lastActiveSyncAt = baseStart,
        activeSessionRevision = revision
    )
}
