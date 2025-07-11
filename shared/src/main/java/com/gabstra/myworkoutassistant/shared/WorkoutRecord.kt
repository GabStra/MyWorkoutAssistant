package com.gabstra.myworkoutassistant.shared

import androidx.room.Entity
import androidx.room.PrimaryKey
import java.util.UUID

@Entity(tableName = "workout_record")
data class WorkoutRecord (
    @PrimaryKey(autoGenerate = false)
    val id: UUID,
    val workoutId: UUID,
    val workoutHistoryId: UUID,
    val setIndex: UInt,
    val exerciseId: UUID,
)