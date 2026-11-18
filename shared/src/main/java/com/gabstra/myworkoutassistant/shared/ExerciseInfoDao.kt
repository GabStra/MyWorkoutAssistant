package com.gabstra.myworkoutassistant.shared

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction
import java.util.UUID

@Dao
interface ExerciseInfoDao {
    @Query("SELECT * FROM exercise_info WHERE id = :id")
    suspend fun getExerciseInfoById(id: UUID): ExerciseInfo?

    @Query("SELECT * FROM exercise_info WHERE id IN (:ids)")
    suspend fun getExerciseInfosByIds(ids: List<UUID>): List<ExerciseInfo>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(exerciseInfo: ExerciseInfo)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(vararg exerciseInfos: ExerciseInfo)

    @Query("DELETE FROM exercise_info WHERE id = :id")
    suspend fun deleteById(id: UUID)

    @Query("DELETE FROM exercise_info")
    suspend fun deleteAll()

    @Query("UPDATE exercise_info SET successfulSessionCounter = :successfulSessionCounter, version = version + 1 WHERE id = :id")
    suspend fun updateSuccessfulSessionCounter(id: UUID, successfulSessionCounter: UInt)

    @Query("UPDATE exercise_info SET sessionFailedCounter = :sessionFailedCounter, version = version + 1 WHERE id = :id")
    suspend fun updateSessionFailedCounter(id: UUID, sessionFailedCounter: UInt)

    @Query("UPDATE exercise_info SET lastSessionWasDeload = :lastSessionWasDeload, version = version + 1 WHERE id = :id")
    suspend fun updateLastSessionWasDeload(id: UUID, lastSessionWasDeload: Boolean)

    @Query("SELECT * FROM exercise_info")
    suspend fun getAllExerciseInfos(): List<ExerciseInfo>

    @Query("UPDATE exercise_info SET version = version + 1 WHERE id = :id")
    suspend fun raiseVersionById(id: UUID)

    @Transaction
    suspend fun insertAllWithVersionCheck(vararg exerciseInfos: ExerciseInfo) {
        if (exerciseInfos.isEmpty()) return
        // One read + one bulk write; the per-row lookup cost ~260ms per row on Wear.
        val existingById = getAllExerciseInfos().associateBy { it.id }
        val toWrite = exerciseInfos.filter { exerciseInfo ->
            val existingExerciseInfo = existingById[exerciseInfo.id]
            existingExerciseInfo == null || exerciseInfo.version >= existingExerciseInfo.version
        }
        if (toWrite.isNotEmpty()) insertAll(*toWrite.toTypedArray())
    }
}
