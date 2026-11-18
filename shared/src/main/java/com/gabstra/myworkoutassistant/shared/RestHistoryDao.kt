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

    @Transaction
    suspend fun replaceAllForWorkoutHistory(
        workoutHistoryId: UUID,
        restHistories: List<RestHistory>
    ) {
        deleteByWorkoutHistoryId(workoutHistoryId)
        insertAllWithVersionCheck(*restHistories.toTypedArray())
    }

    @Query("DELETE FROM rest_history WHERE workoutComponentId = :workoutComponentId")
    suspend fun deleteByWorkoutComponentId(workoutComponentId: UUID)

    @Query("DELETE FROM rest_history")
    suspend fun deleteAll()

    @Query("SELECT * FROM rest_history")
    suspend fun getAll(): List<RestHistory>

    @Transaction
    suspend fun insertAllWithVersionCheck(vararg items: RestHistory) {
        if (items.isEmpty()) return
        // One read + one bulk write instead of a SELECT/INSERT round-trip per row.
        val existingById = getAll().associateBy { it.id }
        val toWrite = items.filter { rest ->
            val existing = existingById[rest.id]
            existing == null || rest.version >= existing.version
        }
        if (toWrite.isNotEmpty()) insertAll(*toWrite.toTypedArray())
    }

    @Query("SELECT * FROM rest_history WHERE id = :id")
    suspend fun getById(id: UUID): RestHistory?
}
