package com.gabstra.myworkoutassistant.shared


import androidx.room.Dao;
import androidx.room.Insert;
import androidx.room.OnConflictStrategy;
import androidx.room.Query;
import java.time.LocalDate
import java.util.UUID

@Dao
interface WorkoutHistoryDao {

    @Query("SELECT * FROM workout_history WHERE id = :id")
    suspend fun getWorkoutHistoryById(id: Int): WorkoutHistory?

    //create a query to check if a workout history exists for a specific workout that returns a bool
    @Query("SELECT EXISTS(SELECT * FROM workout_history WHERE workoutId = :workoutId)")
    suspend fun workoutHistoryExists(workoutId: UUID): Boolean

    @Query("SELECT * FROM workout_history WHERE workoutId = :workoutId ORDER BY date DESC LIMIT 1")
    suspend fun getLatestWorkoutHistoryByWorkoutId(workoutId: UUID): WorkoutHistory?

    @Query("SELECT * FROM workout_history")
    suspend fun getAllWorkoutHistories(): List<WorkoutHistory>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(workoutHistory: WorkoutHistory): Long  // returns new row id

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(vararg workoutHistories: WorkoutHistory)

    @Query("SELECT * FROM workout_history WHERE workoutId = :workoutId")
    fun getWorkoutsByWorkoutId(workoutId: UUID): List<WorkoutHistory>

    @Query("SELECT * FROM workout_history WHERE workoutId = :workoutId ORDER BY date")
    fun getWorkoutsByWorkoutIdByDateAsc(workoutId: UUID): List<WorkoutHistory>

    @Query("SELECT * FROM workout_history WHERE workoutId = :workoutId AND date = :date")
    fun getWorkoutsByWorkoutIdAndDate(workoutId: UUID, date: LocalDate): List<WorkoutHistory>

    @Query("DELETE FROM workout_history WHERE id = :id")
    suspend fun deleteById(id: Int)

    @Query("DELETE FROM workout_history")
    suspend fun deleteAll()

    //delete all workout history for a specific workout
    @Query("DELETE FROM workout_history WHERE workoutId = :workoutId")
    suspend fun deleteAllByWorkoutId(workoutId: UUID)
}