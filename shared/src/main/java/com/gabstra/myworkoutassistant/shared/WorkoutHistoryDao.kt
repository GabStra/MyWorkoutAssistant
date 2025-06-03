package com.gabstra.myworkoutassistant.shared


import androidx.room.Dao;
import androidx.room.Insert;
import androidx.room.OnConflictStrategy;
import androidx.room.Query;
import androidx.room.Transaction
import java.time.LocalDate
import java.time.LocalTime
import java.util.UUID

@Dao
interface WorkoutHistoryDao {

    @Query("SELECT * FROM workout_history WHERE id = :id")
    suspend fun getWorkoutHistoryById(id: UUID): WorkoutHistory?

    //create a query to check if a workout history exists for a specific workout that returns a bool
    @Query("SELECT EXISTS(SELECT * FROM workout_history WHERE workoutId = :workoutId)")
    suspend fun workoutHistoryExistsByWorkoutId(workoutId: UUID): Boolean

    @Query("SELECT * FROM workout_history WHERE workoutId = :workoutId AND isDone = :isDone ORDER BY date DESC LIMIT 1")
    suspend fun getLatestWorkoutHistoryByWorkoutId(workoutId: UUID,isDone: Boolean = true): WorkoutHistory?

    @Query("SELECT * FROM workout_history WHERE hasBeenSentToHealth = :hasBeenSentToHealth")
    suspend fun getWorkoutHistoriesByHasBeenSentToHealth(hasBeenSentToHealth: Boolean): List<WorkoutHistory>

    @Query("SELECT * FROM workout_history")
    suspend fun getAllWorkoutHistories(): List<WorkoutHistory>

    //get all workoutHistories with isDone = true
    @Query("SELECT * FROM workout_history WHERE isDone = :isDone")
    suspend fun getAllWorkoutHistoriesByIsDone(isDone: Boolean = true): List<WorkoutHistory>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(workoutHistory: WorkoutHistory)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(vararg workoutHistories: WorkoutHistory)

    @Query("SELECT * FROM workout_history WHERE workoutId = :workoutId")
    fun getWorkoutsByWorkoutId(workoutId: UUID): List<WorkoutHistory>

    @Query("SELECT * FROM workout_history WHERE workoutId = :workoutId ORDER BY date")
    fun getWorkoutsByWorkoutIdByDateAsc(workoutId: UUID): List<WorkoutHistory>

    @Query("SELECT * FROM workout_history WHERE workoutId = :workoutId AND date = :date")
    fun getWorkoutsByWorkoutIdAndDate(workoutId: UUID, date: LocalDate): List<WorkoutHistory>

    @Query("DELETE FROM workout_history WHERE id = :id")
    suspend fun deleteById(id: UUID)

    @Query("DELETE FROM workout_history")
    suspend fun deleteAll()

    @Query("DELETE FROM workout_history WHERE isDone = :isDone")
    suspend fun deleteAllUnfinished(isDone: Boolean = false)

    //get all unfinished workout histories
    @Query("SELECT * FROM workout_history WHERE isDone = :isDone")
    suspend fun getAllUnfinishedWorkoutHistories(isDone: Boolean = false): List<WorkoutHistory>

    //delete all workout history for a specific workout
    @Query("DELETE FROM workout_history WHERE workoutId = :workoutId")
    suspend fun deleteAllByWorkoutId(workoutId: UUID)

    //add one to update workout histories
    @Query("UPDATE workout_history SET isDone = :isDone WHERE id = :id")
    suspend fun updateIsDone(id: UUID, isDone: Boolean)

    @Query("UPDATE workout_history SET hasBeenSentToHealth = :hasBeenSentToHealth WHERE id = :id")
    suspend fun updateHasBeenSentToHealth(id: UUID, hasBeenSentToHealth: Boolean)

    //add one to update every thing
    @Query("UPDATE workout_history SET workoutId = :workoutId, date = :date, time = :time, duration = :duration, heartBeatRecords = :heartBeatRecords, isDone = :isDone WHERE id = :id")
    suspend fun updateWorkoutHistory(id: UUID, workoutId: UUID, date: LocalDate, time: LocalTime, duration: Int, heartBeatRecords: List<Int>, isDone: Boolean)

    @Transaction
    suspend fun insertWithVersionCheck(workoutHistory: WorkoutHistory) {
        val existingWorkoutHistory = getWorkoutHistoryById(workoutHistory.id)
        if (existingWorkoutHistory == null || workoutHistory.version >= existingWorkoutHistory.version) {
            insert(workoutHistory)
        }
    }

    @Transaction
    suspend fun insertAllWithVersionCheck(vararg workoutHistories: WorkoutHistory) {
        workoutHistories.forEach { workoutHistory ->
            val existingWorkoutHistory = getWorkoutHistoryById(workoutHistory.id)
            if (existingWorkoutHistory == null || workoutHistory.version >= existingWorkoutHistory.version) {
                insert(workoutHistory)
            }
        }
    }
}