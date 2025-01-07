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

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(exerciseInfo: ExerciseInfo)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(vararg exerciseInfos: ExerciseInfo)

    @Query("DELETE FROM exercise_info WHERE id = :id")
    suspend fun deleteById(id: UUID)

    @Query("DELETE FROM exercise_info")
    suspend fun deleteAll()

    @Query("UPDATE exercise_info SET bestVolume = :bestVolume, version = version + 1 WHERE id = :id")
    suspend fun updateBestVolume(id: UUID, bestVolume: Double)

    @Query("UPDATE exercise_info SET oneRepMax = :oneRepMax, version = version + 1 WHERE id = :id")
    suspend fun updateOneRepMax(id: UUID, oneRepMax: Double)

    @Query("UPDATE exercise_info SET successfulSessionCounter = :successfulSessionCounter, version = version + 1 WHERE id = :id")
    suspend fun updateSuccessfulSessionCounter(id: UUID, successfulSessionCounter: UInt)

    @Query("UPDATE exercise_info SET volumeLastSuccessfulSession = :volumeLastSuccessfulSession, version = version + 1 WHERE id = :id")
    suspend fun updateVolumeLastSuccessfulSession(id: UUID, volumeLastSuccessfulSession: Double)

    @Query("UPDATE exercise_info SET sessionFailedCounter = :sessionFailedCounter, version = version + 1 WHERE id = :id")
    suspend fun updateSessionFailedCounter(id: UUID, sessionFailedCounter: UInt)

    @Query("UPDATE exercise_info SET previousSessionWasDeload = :previousSessionWasDeload, version = version + 1 WHERE id = :id")
    suspend fun updatePreviousSessionWasDeload(id: UUID, previousSessionWasDeload: Boolean)

    @Query("SELECT * FROM exercise_info")
    suspend fun getAllExerciseInfos(): List<ExerciseInfo>

    @Query("UPDATE exercise_info SET version = version + 1 WHERE id = :id")
    suspend fun raiseVersionById(id: UUID)

    @Transaction
    suspend fun insertAllWithVersionCheck(vararg exerciseInfos: ExerciseInfo) {
        exerciseInfos.forEach { exerciseInfo ->
            val existingExerciseInfo = getExerciseInfoById(exerciseInfo.id)
            if (existingExerciseInfo == null || exerciseInfo.version >= existingExerciseInfo.version) {
                insert(exerciseInfo)
            }
        }
    }
}