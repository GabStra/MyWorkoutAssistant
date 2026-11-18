package com.gabstra.myworkoutassistant.shared.workout.model

import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import java.util.UUID

/**
 * Snapshot of a started-but-not-finished workout (open history + ids) used for Wear recovery
 * and sync. User-visible copy for this flow lives in `strings_recovery.xml`.
 */
data class IncompleteWorkout(
    val workoutHistory: WorkoutHistory,
    val workoutName: String,
    val workoutId: UUID
)
