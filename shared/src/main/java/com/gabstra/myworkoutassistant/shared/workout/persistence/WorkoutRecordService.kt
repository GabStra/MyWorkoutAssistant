package com.gabstra.myworkoutassistant.shared.workout.persistence

import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutRecord
import com.gabstra.myworkoutassistant.shared.WorkoutRecordDao
import com.gabstra.myworkoutassistant.shared.workout.model.InterruptedWorkout
import com.gabstra.myworkoutassistant.shared.workout.model.SessionOwnerDevice
import com.gabstra.myworkoutassistant.shared.workout.model.WorkoutSessionStatus
import com.gabstra.myworkoutassistant.shared.workout.model.resolveWorkoutSessionStatus
import java.time.LocalDateTime
import java.util.UUID

internal class WorkoutRecordService(
    private val workoutRecordDao: () -> WorkoutRecordDao,
    private val workoutHistoryDao: () -> WorkoutHistoryDao
) {
    data class WorkoutRecordState(
        val workoutRecord: WorkoutRecord?,
        val hasWorkoutRecord: Boolean,
        val workoutHistory: WorkoutHistory? = null,
        val sessionStatus: WorkoutSessionStatus? = null,
    )

    suspend fun resolveWorkoutRecord(workoutId: UUID): WorkoutRecordState {
        var workoutRecord = workoutRecordDao().getWorkoutRecordByWorkoutId(workoutId)
        var workoutHistory: WorkoutHistory? = null
        if (workoutRecord != null) {
            workoutHistory = workoutHistoryDao().getWorkoutHistoryById(workoutRecord.workoutHistoryId)
            if (workoutHistory == null) {
                workoutRecordDao().deleteById(workoutRecord.id)
                workoutRecord = null
            }
        }
        return WorkoutRecordState(
            workoutRecord = workoutRecord,
            hasWorkoutRecord = workoutRecord != null,
            workoutHistory = workoutHistory,
            sessionStatus = if (workoutRecord != null && workoutHistory != null) {
                resolveWorkoutSessionStatus(workoutHistory, workoutRecord)
            } else {
                null
            }
        )
    }

    suspend fun upsertWorkoutRecord(
        existingRecord: WorkoutRecord?,
        workoutId: UUID,
        workoutHistoryId: UUID?,
        exerciseId: UUID,
        setIndex: UInt,
        ownerDevice: SessionOwnerDevice,
        lastActiveSyncAt: LocalDateTime,
        lastKnownSessionState: String? = null,
    ): WorkoutRecord? {
        val updatedRecord = when {
            existingRecord == null && workoutHistoryId != null -> {
                WorkoutRecord(
                    id = UUID.randomUUID(),
                    workoutId = workoutId,
                    exerciseId = exerciseId,
                    setIndex = setIndex,
                    workoutHistoryId = workoutHistoryId,
                    ownerDevice = ownerDevice.name,
                    lastActiveSyncAt = lastActiveSyncAt,
                    activeSessionRevision = 1u,
                    lastKnownSessionState = lastKnownSessionState,
                )
            }
            existingRecord != null -> {
                existingRecord.copy(
                    exerciseId = exerciseId,
                    setIndex = setIndex,
                    ownerDevice = ownerDevice.name,
                    lastActiveSyncAt = lastActiveSyncAt,
                    activeSessionRevision = existingRecord.activeSessionRevision.inc(),
                    lastKnownSessionState = lastKnownSessionState,
                )
            }
            else -> null
        }

        if (updatedRecord != null) {
            workoutRecordDao().insert(updatedRecord)
        }
        return updatedRecord
    }

    suspend fun adoptWorkoutRecord(
        existingRecord: WorkoutRecord,
        ownerDevice: SessionOwnerDevice,
        lastActiveSyncAt: LocalDateTime,
        lastKnownSessionState: String? = null
    ): WorkoutRecord {
        val updatedRecord = existingRecord.copy(
            ownerDevice = ownerDevice.name,
            lastActiveSyncAt = lastActiveSyncAt,
            activeSessionRevision = existingRecord.activeSessionRevision.inc(),
            lastKnownSessionState = lastKnownSessionState,
        )
        workoutRecordDao().insert(updatedRecord)
        return updatedRecord
    }

    suspend fun deleteWorkoutRecord(recordId: UUID) {
        workoutRecordDao().deleteById(recordId)
    }

    suspend fun getInterruptedWorkouts(workouts: List<Workout>): List<InterruptedWorkout> {
        val incompleteHistories = workoutHistoryDao().getAllUnfinishedWorkoutHistories(isDone = false)
        val workoutRecordsByHistoryId = workoutRecordDao().getAll()
            .associateBy { record -> record.workoutHistoryId }

        val groupedByWorkoutId = incompleteHistories
            .groupBy { it.workoutId }
            .mapValues { (_, histories) ->
                histories.maxByOrNull { it.startTime } ?: histories.first()
            }

        return groupedByWorkoutId.values.mapNotNull { workoutHistory ->
            val sessionStatus = resolveWorkoutSessionStatus(
                workoutHistory = workoutHistory,
                workoutRecord = workoutRecordsByHistoryId[workoutHistory.id]
            )
            if (sessionStatus != WorkoutSessionStatus.INTERRUPTED) {
                return@mapNotNull null
            }

            val workout = workouts.find { it.id == workoutHistory.workoutId }
                ?: workouts.find { it.globalId == workoutHistory.globalId }
                ?: return@mapNotNull null

            InterruptedWorkout(
                workoutHistory = workoutHistory,
                workoutName = workout.name,
                workoutId = workout.id
            )
        }
    }
}

