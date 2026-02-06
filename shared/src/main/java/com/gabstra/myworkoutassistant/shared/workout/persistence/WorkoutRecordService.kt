package com.gabstra.myworkoutassistant.shared.workout.persistence

import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutRecord
import com.gabstra.myworkoutassistant.shared.WorkoutRecordDao
import java.util.UUID

internal class WorkoutRecordService(
    private val workoutRecordDao: () -> WorkoutRecordDao,
    private val workoutHistoryDao: () -> WorkoutHistoryDao
) {
    data class WorkoutRecordState(
        val workoutRecord: WorkoutRecord?,
        val hasWorkoutRecord: Boolean
    )

    data class IncompleteWorkout(
        val workoutHistory: WorkoutHistory,
        val workoutName: String,
        val workoutId: UUID
    )

    suspend fun resolveWorkoutRecord(workoutId: UUID): WorkoutRecordState {
        var workoutRecord = workoutRecordDao().getWorkoutRecordByWorkoutId(workoutId)
        if (workoutRecord != null) {
            val workoutHistory = workoutHistoryDao().getWorkoutHistoryById(workoutRecord.workoutHistoryId)
            if (workoutHistory == null) {
                workoutRecordDao().deleteById(workoutRecord.id)
                workoutRecord = null
            }
        }
        return WorkoutRecordState(
            workoutRecord = workoutRecord,
            hasWorkoutRecord = workoutRecord != null
        )
    }

    suspend fun upsertWorkoutRecord(
        existingRecord: WorkoutRecord?,
        workoutId: UUID,
        workoutHistoryId: UUID?,
        exerciseId: UUID,
        setIndex: UInt
    ): WorkoutRecord? {
        val updatedRecord = when {
            existingRecord == null && workoutHistoryId != null -> {
                WorkoutRecord(
                    id = UUID.randomUUID(),
                    workoutId = workoutId,
                    exerciseId = exerciseId,
                    setIndex = setIndex,
                    workoutHistoryId = workoutHistoryId
                )
            }
            existingRecord != null -> {
                existingRecord.copy(
                    exerciseId = exerciseId,
                    setIndex = setIndex
                )
            }
            else -> null
        }

        if (updatedRecord != null) {
            workoutRecordDao().insert(updatedRecord)
        }
        return updatedRecord
    }

    suspend fun deleteWorkoutRecord(recordId: UUID) {
        workoutRecordDao().deleteById(recordId)
    }

    suspend fun getIncompleteWorkouts(workouts: List<Workout>): List<IncompleteWorkout> {
        val incompleteHistories = workoutHistoryDao().getAllUnfinishedWorkoutHistories(isDone = false)

        val groupedByWorkoutId = incompleteHistories
            .groupBy { it.workoutId }
            .mapValues { (_, histories) ->
                histories.maxByOrNull { it.startTime } ?: histories.first()
            }

        return groupedByWorkoutId.values.mapNotNull { workoutHistory ->
            val workout = workouts.find { it.id == workoutHistory.workoutId }
                ?: workouts.find { it.globalId == workoutHistory.globalId }
                ?: return@mapNotNull null

            val workoutRecord = workoutRecordDao().getWorkoutRecordByWorkoutId(workout.id)
            if (workoutRecord == null || workoutRecord.workoutHistoryId != workoutHistory.id) {
                return@mapNotNull null
            }

            IncompleteWorkout(
                workoutHistory = workoutHistory,
                workoutName = workout.name,
                workoutId = workout.id
            )
        }
    }
}


