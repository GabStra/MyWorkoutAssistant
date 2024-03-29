package com.gabstra.myworkoutassistant.shared

import androidx.room.Entity
import androidx.room.PrimaryKey
import java.time.LocalDate
import java.util.UUID

@Entity(tableName = "workout_history")
data class WorkoutHistory(
    @PrimaryKey(autoGenerate = true)
    val id: Int = 0,
    val workoutId: UUID,
    val date: LocalDate,
    val duration: Int,
    val heartBeatRecords: List<Int>
)
