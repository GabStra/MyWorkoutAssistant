package com.gabstra.myworkoutassistant.shared

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction
import java.util.UUID

@Dao
interface ExerciseSessionProgressionDao {
    @Query("SELECT * FROM exercise_session_progression WHERE id = :id")
    suspend fun getExerciseSessionProgressionById(id: UUID): ExerciseSessionProgression?

    @Query("SELECT * FROM exercise_session_progression WHERE workoutHistoryId = :workoutHistoryId")
    suspend fun getByWorkoutHistoryId(workoutHistoryId: UUID): List<ExerciseSessionProgression>

    @Query("SELECT * FROM exercise_session_progression WHERE workoutHistoryId = :workoutHistoryId AND exerciseId = :exerciseId")
    suspend fun getByWorkoutHistoryIdAndExerciseId(workoutHistoryId: UUID, exerciseId: UUID): ExerciseSessionProgression?

    @Query("SELECT * FROM exercise_session_progression WHERE exerciseId = :exerciseId ORDER BY workoutHistoryId")
    suspend fun getByExerciseId(exerciseId: UUID): List<ExerciseSessionProgression>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(progression: ExerciseSessionProgression)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(vararg progressions: ExerciseSessionProgression)

    @Query("DELETE FROM exercise_session_progression WHERE workoutHistoryId = :workoutHistoryId")
    suspend fun deleteByWorkoutHistoryId(workoutHistoryId: UUID)

    @Query("DELETE FROM exercise_session_progression WHERE exerciseId = :exerciseId")
    suspend fun deleteByExerciseId(exerciseId: UUID)

    @Query("SELECT * FROM exercise_session_progression")
    suspend fun getAllExerciseSessionProgressions(): List<ExerciseSessionProgression>

    @Query("DELETE FROM exercise_session_progression")
    suspend fun deleteAll()

    @Transaction
    suspend fun insertAllWithVersionCheck(vararg progressions: ExerciseSessionProgression) {
        progressions.forEach { progression ->
            val existingProgression = getExerciseSessionProgressionById(progression.id)
            if (existingProgression == null || progression.version >= existingProgression.version) {
                insert(progression)
            }
        }
    }
}

