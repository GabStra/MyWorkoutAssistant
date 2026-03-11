package com.gabstra.myworkoutassistant.shared

import androidx.room.ForeignKey
import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import java.time.LocalDateTime
import java.util.UUID

@Entity(
    tableName = "set_history",
    foreignKeys = [
        ForeignKey(
            entity = WorkoutHistory::class,
            parentColumns = ["id"],
            childColumns = ["workoutHistoryId"],
            onDelete = ForeignKey.CASCADE
        )
    ],
    indices = [
        Index("workoutHistoryId"),
        Index(value = ["workoutHistoryId", "executionSequence"]),
        Index(value = ["workoutHistoryId", "exerciseId", "executionSequence"]),
        Index(value = ["workoutHistoryId", "supersetId", "supersetRound", "supersetExerciseIndex"])
    ]
)

data class SetHistory(
    @PrimaryKey(autoGenerate = false)
    val id: UUID,
    val workoutHistoryId: UUID? = null,
    val exerciseId : UUID? = null,
    /**
     * Snapshot of the equipment context at the time this set was recorded.
     * These fields are nullable so older rows (before this feature) remain valid.
     */
    val equipmentIdSnapshot: UUID? = null,
    val equipmentNameSnapshot: String? = null,
    /**
     * Simple string representation of the equipment type (e.g. \"BARBELL\", \"DUMBBELLS\").
     * Stored as String to avoid additional Room type converters.
     */
    val equipmentTypeSnapshot: String? = null,
    val setId: UUID,
    val order: UInt,
    val startTime: LocalDateTime?,
    val endTime: LocalDateTime?,
    val setData: SetData,
    val skipped: Boolean,
    val supersetId: UUID? = null,
    val supersetRound: UInt? = null,
    val supersetExerciseIndex: UInt? = null,
    val executionSequence: UInt? = null,
    val version: UInt = 0u
)
