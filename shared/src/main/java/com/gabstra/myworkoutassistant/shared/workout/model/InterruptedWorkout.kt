package com.gabstra.myworkoutassistant.shared.workout.model

import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import java.util.UUID

/**
 * Represents a workout that was started but not finished (interrupted).
 * Aligns with InterruptedWorkoutCopy for UI strings ("Interrupted workout", etc.).
 */
data class InterruptedWorkout(
    val workoutHistory: WorkoutHistory,
    val workoutName: String,
    val workoutId: UUID
)
