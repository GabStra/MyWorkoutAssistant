package com.gabstra.myworkoutassistant.shared

import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index
import androidx.room.PrimaryKey
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
import com.gabstra.myworkoutassistant.shared.utils.Ternary
import com.gabstra.myworkoutassistant.shared.workout.state.ProgressionState
import java.util.UUID

@Entity(
    tableName = "exercise_session_progression",
    foreignKeys = [
        ForeignKey(
            entity = WorkoutHistory::class,
            parentColumns = ["id"],
            childColumns = ["workoutHistoryId"],
            onDelete = ForeignKey.CASCADE
        )
    ],
    indices = [Index("workoutHistoryId"), Index("exerciseId")]
)
data class ExerciseSessionProgression(
    @PrimaryKey(autoGenerate = false)
    val id: UUID,
    val workoutHistoryId: UUID,
    val exerciseId: UUID,
    val expectedSets: List<SimpleSet>,
    val progressionState: ProgressionState,
    val vsExpected: Ternary,
    val vsPrevious: Ternary,
    val previousSessionVolume: Double,
    val expectedVolume: Double,
    val executedVolume: Double,
    val version: UInt = 0u
)


