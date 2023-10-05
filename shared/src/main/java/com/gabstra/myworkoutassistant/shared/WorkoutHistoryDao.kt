package com.gabstra.myworkoutassistant.shared


import androidx.room.Dao;
import androidx.room.Insert;
import androidx.room.OnConflictStrategy;
import androidx.room.Query;
import java.time.LocalDate

@Dao
interface WorkoutHistoryDao {

    @Query("SELECT * FROM workout_history WHERE id = :id")
    suspend fun getWorkoutHistoryById(id: Int): WorkoutHistory?

    @Query("SELECT * FROM workout_history WHERE name = :name ORDER BY date DESC LIMIT 1")
    suspend fun getLatestWorkoutHistoryByName(name: String): WorkoutHistory?

    @Query("SELECT * FROM workout_history ORDER BY date DESC")
    suspend fun getAllWorkoutHistories(): List<WorkoutHistory>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(workoutHistory: WorkoutHistory): Long  // returns new row id

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(vararg workoutHistories: WorkoutHistory)

    @Query("SELECT * FROM workout_history WHERE name = :name AND date = :date")
    fun getWorkoutsByNameAndDate(name: String, date: LocalDate): List<WorkoutHistory>


    @Query("DELETE FROM workout_history WHERE id = :id")
    suspend fun deleteById(id: Int)
}