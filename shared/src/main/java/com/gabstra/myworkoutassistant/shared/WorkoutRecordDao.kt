package com.gabstra.myworkoutassistant.shared

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import java.util.UUID

@Dao
interface WorkoutRecordDao {
    @Query("SELECT * FROM workout_record WHERE workoutId = :workoutId")
    suspend fun getWorkoutRecordByWorkoutId(workoutId: UUID): WorkoutRecord?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(workoutRecord: WorkoutRecord)

    @Query("DELETE FROM workout_record WHERE id = :id")
    suspend fun deleteById(id: UUID)
}