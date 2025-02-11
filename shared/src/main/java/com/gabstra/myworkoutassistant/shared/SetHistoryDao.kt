package com.gabstra.myworkoutassistant.shared

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction
import java.util.UUID

@Dao
interface SetHistoryDao {
    @Query("SELECT * FROM set_history WHERE id = :id")
    suspend fun getSetHistoryById(id: UUID): SetHistory?

    @Query("SELECT * FROM set_history")
    suspend fun getAllSetHistories(): List<SetHistory>

    @Query("SELECT * FROM set_history WHERE workoutHistoryId = :workoutHistoryId")
    suspend fun getSetHistoriesByWorkoutHistoryId(workoutHistoryId: UUID): List<SetHistory>

    @Query("SELECT * FROM set_history WHERE workoutHistoryId = :workoutHistoryId AND setId = :setId")
    suspend fun getSetHistoryByWorkoutHistoryIdAndSetId(workoutHistoryId: UUID, setId: UUID): SetHistory?

    @Query("SELECT * FROM set_history WHERE exerciseId = :exerciseId")
    suspend fun getSetHistoriesByExerciseId(exerciseId: UUID): List<SetHistory>

    @Query("SELECT * FROM set_history WHERE workoutHistoryId = :workoutHistoryId AND exerciseId = :exerciseId")
    suspend fun getSetHistoriesByWorkoutHistoryIdAndExerciseId(workoutHistoryId: UUID,exerciseId: UUID): List<SetHistory>


    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(setHistory: SetHistory)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(vararg setHistories: SetHistory)

    @Query("DELETE FROM set_history WHERE workoutHistoryId = :workoutHistoryId")
    suspend fun deleteByWorkoutHistoryId(workoutHistoryId: UUID)

    @Query("DELETE FROM set_history WHERE exerciseId = :exerciseId")
    suspend fun deleteByExerciseId(exerciseId: UUID)

    @Query("DELETE FROM set_history")
    suspend fun deleteAll()

    @Query("UPDATE set_history SET version = version + 1 WHERE id = :id")
    suspend fun raiseVersionById(id: UUID)

    @Transaction
    suspend fun insertAllWithVersionCheck(vararg setHistories: SetHistory) {
        setHistories.forEach { setHistory ->
            val existingSetHistory = getSetHistoryById(setHistory.id)
            if (existingSetHistory == null || setHistory.version >= existingSetHistory.version) {
                insert(setHistory)
            }
        }
    }
}

