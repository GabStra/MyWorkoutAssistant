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
    suspend fun getWorkoutRecordByWorkoutId(workoutId: UUID): WorkoutRecord?

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
}