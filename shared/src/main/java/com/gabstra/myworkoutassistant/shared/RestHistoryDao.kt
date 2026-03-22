package com.gabstra.myworkoutassistant.shared

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction
import java.util.UUID

@Dao
interface RestHistoryDao {
    @Query("SELECT * FROM rest_history WHERE workoutHistoryId = :workoutHistoryId")
    suspend fun getByWorkoutHistoryId(workoutHistoryId: UUID): List<RestHistory>

    @Query(
        """
        SELECT * FROM rest_history
        WHERE workoutHistoryId = :workoutHistoryId
        ORDER BY
            CASE WHEN executionSequence IS NULL THEN 1 ELSE 0 END,
            executionSequence ASC,
            startTime ASC,
            "order" ASC
        """
    )
    suspend fun getByWorkoutHistoryIdOrdered(workoutHistoryId: UUID): List<RestHistory>

    @Query("SELECT * FROM rest_history WHERE workoutHistoryId = :workoutHistoryId AND exerciseId = :exerciseId")
    suspend fun getByWorkoutHistoryIdAndExerciseId(workoutHistoryId: UUID, exerciseId: UUID): List<RestHistory>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(restHistory: RestHistory)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(vararg items: RestHistory)

    @Query("DELETE FROM rest_history WHERE workoutHistoryId = :workoutHistoryId")
    suspend fun deleteByWorkoutHistoryId(workoutHistoryId: UUID)

    @Query("DELETE FROM rest_history WHERE workoutComponentId = :workoutComponentId")
    suspend fun deleteByWorkoutComponentId(workoutComponentId: UUID)

    @Query("DELETE FROM rest_history")
    suspend fun deleteAll()

    @Query("SELECT * FROM rest_history")
    suspend fun getAll(): List<RestHistory>

    @Transaction
    suspend fun insertAllWithVersionCheck(vararg items: RestHistory) {
        items.forEach { rest ->
            val existing = getById(rest.id)
            if (existing == null || rest.version >= existing.version) {
                insert(rest)
            }
        }
    }

    @Query("SELECT * FROM rest_history WHERE id = :id")
    suspend fun getById(id: UUID): RestHistory?
}
