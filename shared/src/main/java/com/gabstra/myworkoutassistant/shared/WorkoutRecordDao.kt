package com.gabstra.myworkoutassistant.shared

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import java.util.UUID

@Dao
interface WorkoutRecordDao {
    //get all
    @Query("SELECT * FROM workout_record")
    suspend fun getAll(): List<WorkoutRecord>

    @Query("SELECT * FROM workout_record WHERE workoutId = :workoutId")
    suspend fun getWorkoutRecordsByWorkoutId(workoutId: UUID): List<WorkoutRecord>

    suspend fun getWorkoutRecordByWorkoutId(workoutId: UUID): WorkoutRecord? {
        val records = getWorkoutRecordsByWorkoutId(workoutId)
        require(records.size <= 1) {
            buildString {
                append("Expected at most one workout_record row for workoutId=")
                append(workoutId)
                append(", found ")
                append(records.size)
                append(": ")
                append(records.joinToString { "${it.id}:${it.workoutHistoryId}" })
            }
        }
        return records.singleOrNull()
    }

    @Query("SELECT * FROM workout_record WHERE workoutHistoryId = :workoutHistoryId LIMIT 1")
    suspend fun getWorkoutRecordByWorkoutHistoryId(workoutHistoryId: UUID): WorkoutRecord?

    @Query("SELECT workoutId FROM workout_record GROUP BY workoutId HAVING COUNT(*) > 1")
    suspend fun getDuplicateWorkoutIds(): List<UUID>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(workoutRecord: WorkoutRecord)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(vararg workoutRecords: WorkoutRecord)

    @Query("DELETE FROM workout_record WHERE id = :id")
    suspend fun deleteById(id: UUID)

    @Query("DELETE FROM workout_record")
    suspend fun deleteAll()

    //delete workout record by workout id
    @Query("DELETE FROM workout_record WHERE workoutId = :workoutId")
    suspend fun deleteByWorkoutId(workoutId: UUID)

    //delete workout record by workout history id
    @Query("DELETE FROM workout_record WHERE workoutHistoryId = :workoutHistoryId")
    suspend fun deleteByWorkoutHistoryId(workoutHistoryId: UUID)

    @Query(
        "DELETE FROM workout_record WHERE workoutHistoryId NOT IN (SELECT id FROM workout_history)"
    )
    suspend fun deleteOrphanedRecords()
}
