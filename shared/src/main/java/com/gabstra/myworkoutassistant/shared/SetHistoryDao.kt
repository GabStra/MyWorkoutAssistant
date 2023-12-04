package com.gabstra.myworkoutassistant.shared

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query

@Dao
interface SetHistoryDao {
    @Query("SELECT * FROM set_history WHERE workoutHistoryId = :workoutHistoryId")
    suspend fun getExerciseHistoriesByWorkoutHistoryId(workoutHistoryId: Int): List<SetHistory>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(setHistory: SetHistory)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(vararg exerciseHistories: SetHistory)

    @Query("DELETE FROM set_history WHERE workoutHistoryId = :workoutHistoryId")
    suspend fun deleteByWorkoutHistoryId(workoutHistoryId: Int)
}

