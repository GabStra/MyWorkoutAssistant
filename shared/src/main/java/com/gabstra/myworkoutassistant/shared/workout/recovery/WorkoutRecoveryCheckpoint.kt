package com.gabstra.myworkoutassistant.shared.workout.recovery

import java.util.UUID

/**
 * Snapshot of the current workout state for process-death recovery.
 * Persisted by platform-specific store (e.g. SharedPreferences on Wear OS).
 */
data class WorkoutRecoveryCheckpoint(
    val workoutId: UUID,
    val workoutHistoryId: UUID?,
    val stateType: RecoveryStateType,
    val isCalibrationSetExecution: Boolean = false,
    val exerciseId: UUID?,
    val setId: UUID?,
    val setIndex: UInt?,
    val restOrder: UInt?,
    val setStartEpochMs: Long?,
    val updatedAtEpochMs: Long
)
