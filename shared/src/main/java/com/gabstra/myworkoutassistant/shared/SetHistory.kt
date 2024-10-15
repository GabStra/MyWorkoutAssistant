package com.gabstra.myworkoutassistant.shared

import androidx.room.Entity
import androidx.room.PrimaryKey

import androidx.room.ForeignKey
import androidx.room.Index
import com.gabstra.myworkoutassistant.shared.setdata.SetData
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
    indices = [Index("workoutHistoryId")]
)

data class SetHistory(
    @PrimaryKey(autoGenerate = false)
    val id: UUID,
    val workoutHistoryId: UUID? = null,
    val exerciseId : UUID? = null,
    val setId: UUID,
    val order: UInt,
    val setData: SetData,
    val skipped: Boolean,
    val version: UInt = 0u
)
