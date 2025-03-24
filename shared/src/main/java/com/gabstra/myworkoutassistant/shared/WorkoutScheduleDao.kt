package com.gabstra.myworkoutassistant.shared

import androidx.room.Dao
import androidx.room.Delete
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Update
import java.util.UUID

@Dao
interface WorkoutScheduleDao {
    @Query("SELECT * FROM workout_schedule")
    suspend fun getAllSchedules(): List<WorkoutSchedule>
    
    @Query("SELECT * FROM workout_schedule WHERE id = :id")
    suspend fun getScheduleById(id: UUID): WorkoutSchedule?
    
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(schedule: WorkoutSchedule)
    
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(vararg schedules: WorkoutSchedule)
    
    @Update
    suspend fun update(schedule: WorkoutSchedule)
    
    @Delete
    suspend fun delete(schedule: WorkoutSchedule)
    
    @Query("DELETE FROM workout_schedule WHERE id = :id")
    suspend fun deleteById(id: UUID)
    
    @Query("DELETE FROM workout_schedule")
    suspend fun deleteAll()
    
    @Query("SELECT * FROM workout_schedule WHERE isEnabled = 1 AND (specificDate IS NULL OR hasExecuted = 0)")
    suspend fun getActiveSchedules(): List<WorkoutSchedule>
    
    @Query("UPDATE workout_schedule SET hasExecuted = 1 WHERE id = :id")
    suspend fun markAsExecuted(id: UUID)
}
