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
    var workoutHistoryId: UUID? = null,
    val exerciseId : UUID,
    val setId: UUID,
    val order: Int,
    val setData: SetData,
    val skipped: Boolean
)
