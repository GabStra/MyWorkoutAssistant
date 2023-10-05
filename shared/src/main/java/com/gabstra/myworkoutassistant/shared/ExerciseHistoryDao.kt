package com.gabstra.myworkoutassistant.shared

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query

@Dao
interface ExerciseHistoryDao {
    @Query("SELECT * FROM exercise_history WHERE workoutHistoryId = :workoutHistoryId")
    suspend fun getExerciseHistoriesByWorkoutHistoryId(workoutHistoryId: Int): List<ExerciseHistory>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(exerciseHistory: ExerciseHistory)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(vararg exerciseHistories: ExerciseHistory)
}

