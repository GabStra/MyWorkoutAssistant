package com.gabstra.myworkoutassistant.shared.workout.model

import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import java.util.UUID

/**
 * Snapshot of a started-but-not-finished workout (open history + ids) used for Wear recovery
 * and sync. Aligns with [com.gabstra.myworkoutassistant.shared.workout.ui.IncompleteWorkoutStrings].
 */
data class IncompleteWorkout(
    val workoutHistory: WorkoutHistory,
    val workoutName: String,
    val workoutId: UUID
)
