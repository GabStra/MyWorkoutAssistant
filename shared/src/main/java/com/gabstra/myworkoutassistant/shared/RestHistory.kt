package com.gabstra.myworkoutassistant.shared

import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index
import androidx.room.PrimaryKey
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import java.time.LocalDateTime
import java.util.UUID

@Entity(
    tableName = "rest_history",
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
        Index(value = ["workoutHistoryId", "executionSequence"])
    ]
)
data class RestHistory(
    @PrimaryKey(autoGenerate = false)
    val id: UUID,
    val workoutHistoryId: UUID? = null,
    val scope: RestHistoryScope,
    val executionSequence: UInt? = null,
    val setData: SetData,
    val startTime: LocalDateTime?,
    val endTime: LocalDateTime?,
    /** Top-level [com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest] id when [scope] is [RestHistoryScope.BETWEEN_WORKOUT_COMPONENTS]. */
    val workoutComponentId: UUID? = null,
    val exerciseId: UUID? = null,
    /** The session [com.gabstra.myworkoutassistant.shared.sets.RestSet] id for this rest. */
    val restSetId: UUID,
    val order: UInt,
    val version: UInt = 0u
)
