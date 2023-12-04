package com.gabstra.myworkoutassistant.shared

import androidx.room.Entity
import androidx.room.PrimaryKey

import androidx.room.ForeignKey
import androidx.room.Index
import com.gabstra.myworkoutassistant.shared.setdata.SetData

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
    @PrimaryKey(autoGenerate = true)
    val id: Int = 0,
    var workoutHistoryId: Int? = null,
    val setHistoryId: String,
    val setData: SetData,
    val skipped: Boolean
)
