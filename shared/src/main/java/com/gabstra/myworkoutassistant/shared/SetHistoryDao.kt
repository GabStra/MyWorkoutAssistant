package com.gabstra.myworkoutassistant.shared

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import java.util.UUID

@Dao
interface SetHistoryDao {
    @Query("SELECT * FROM set_history")
    suspend fun getAllSetHistories(): List<SetHistory>

    @Query("SELECT * FROM set_history WHERE workoutHistoryId = :workoutHistoryId")
    suspend fun getSetHistoriesByWorkoutHistoryId(workoutHistoryId: Int): List<SetHistory>

    @Query("SELECT * FROM set_history WHERE workoutHistoryId = :workoutHistoryId AND setId = :setId")
    suspend fun getSetHistoryByWorkoutHistoryIdAndSetId(workoutHistoryId: Int, setId: Int): SetHistory?

    @Query("SELECT * FROM set_history WHERE exerciseId = :exerciseId")
    suspend fun getSetHistoriesByExerciseId(exerciseId: UUID): List<SetHistory>

    @Query("SELECT * FROM set_history WHERE workoutHistoryId = :workoutHistoryId AND exerciseId = :exerciseId")
    suspend fun getSetHistoriesByWorkoutHistoryIdAndExerciseId(workoutHistoryId: Int,exerciseId: UUID): List<SetHistory>


    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(setHistory: SetHistory)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(vararg setHistories: SetHistory)

    @Query("DELETE FROM set_history WHERE workoutHistoryId = :workoutHistoryId")
    suspend fun deleteByWorkoutHistoryId(workoutHistoryId: Int)

    @Query("DELETE FROM set_history")
    suspend fun deleteAll()
}

