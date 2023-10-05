package com.gabstra.myworkoutassistant.shared

import androidx.room.Entity
import androidx.room.PrimaryKey
import java.time.LocalDate

import androidx.room.ForeignKey

@Entity(
    tableName = "exercise_history",
    foreignKeys = [
        ForeignKey(
            entity = WorkoutHistory::class,
            parentColumns = ["id"],
            childColumns = ["workoutHistoryId"],
            onDelete = ForeignKey.CASCADE
        )
    ]
)

data class ExerciseHistory(
    @PrimaryKey(autoGenerate = true)
    val id: Int = 0,
    var workoutHistoryId: Int? = null,
    val name: String,
    val set: Int,
    val reps: Int,
    val weight: Float?,
    val skipped: Boolean
)
