package com.gabstra.myworkoutassistant.shared

import androidx.room.Entity
import androidx.room.PrimaryKey
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID

@Entity(tableName = "workout_history")
data class WorkoutHistory(
    @PrimaryKey(autoGenerate = false)
    val id: UUID,
    val workoutId: UUID,
    val date: LocalDate,
    val time: LocalTime,
    val startTime: LocalDateTime,
    val duration: Int,
    val heartBeatRecords: List<Int>,
    val isDone : Boolean
)
