package com.gabstra.myworkoutassistant.shared

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
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

    @Query("UPDATE exercise_info SET bestVolume = :bestVolume WHERE id = :id")
    suspend fun updateBestVolume(id: UUID, bestVolume: Double)

    @Query("UPDATE exercise_info SET oneRepMax = :oneRepMax WHERE id = :id")
    suspend fun updateOneRepMax(id: UUID, oneRepMax: Double)

    @Query("SELECT id FROM exercise_info")
    suspend fun getAllExerciseInfoIds(): List<UUID>

    @Query("SELECT * FROM exercise_info")
    suspend fun getAllExerciseInfos(): List<ExerciseInfo>
}