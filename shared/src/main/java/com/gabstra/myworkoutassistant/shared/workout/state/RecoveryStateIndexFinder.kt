package com.gabstra.myworkoutassistant.shared.workout.state

import java.util.UUID

/**
 * Finds the index in [allStates] to recover to given a target state type and checkpoint parameters.
 * Used when resuming a workout after process kill; calibration-specific rules ensure
 * CALIBRATION_LOAD never lands on the calibration Set execution state.
 */
internal object RecoveryStateIndexFinder {

    fun findRecoveryStateIndex(
        allStates: List<WorkoutState>,
        stateType: String,
        exerciseId: UUID?,
        setId: UUID?,
        setIndex: UInt?,
        restOrder: UInt?
    ): Int? {
        fun firstMatching(predicate: (WorkoutState) -> Boolean): Int? {
            val index = allStates.indexOfFirst(predicate)
            return index.takeIf { it >= 0 }
        }

        val normalizedStateType = stateType.uppercase()

        val exactMatch = when (normalizedStateType) {
            "SET" -> firstMatching { state ->
                state is WorkoutState.Set &&
                    (setId == null || state.set.id == setId) &&
                    (exerciseId == null || state.exerciseId == exerciseId) &&
                    (setIndex == null || state.setIndex == setIndex)
            }

            "REST" -> firstMatching { state ->
                state is WorkoutState.Rest &&
                    (setId == null || state.set.id == setId) &&
                    (exerciseId == null || state.exerciseId == exerciseId) &&
                    (restOrder == null || state.order == restOrder)
            }

            "CALIBRATION_LOAD" -> firstMatching { state ->
                state is WorkoutState.CalibrationLoadSelection &&
                    (setId == null || state.calibrationSet.id == setId) &&
                    (exerciseId == null || state.exerciseId == exerciseId) &&
                    (setIndex == null || state.setIndex == setIndex)
            }

            "CALIBRATION_RIR" -> firstMatching { state ->
                state is WorkoutState.CalibrationRIRSelection &&
                    (setId == null || state.calibrationSet.id == setId) &&
                    (exerciseId == null || state.exerciseId == exerciseId) &&
                    (setIndex == null || state.setIndex == setIndex)
            }

            else -> null
        }

        if (exactMatch != null) return exactMatch

        // CALIBRATION_LOAD: only allow CalibrationLoadSelection (never calibration Set execution).
        if (normalizedStateType == "CALIBRATION_LOAD") {
            val loadSelectionFallback = firstMatching { state ->
                state is WorkoutState.CalibrationLoadSelection &&
                    (exerciseId == null || state.exerciseId == exerciseId)
            }
            return loadSelectionFallback
        }

        // Calibration fallback for CALIBRATION_RIR when calibration selection states are missing.
        if (normalizedStateType == "CALIBRATION_RIR") {
            val calibrationSetFallback = firstMatching { state ->
                state is WorkoutState.Set &&
                    state.isCalibrationSet &&
                    (setId == null || state.set.id == setId) &&
                    (exerciseId == null || state.exerciseId == exerciseId) &&
                    (setIndex == null || state.setIndex == setIndex)
            }
            if (calibrationSetFallback != null) return calibrationSetFallback
        }

        val genericSetFallback = firstMatching { state ->
            state is WorkoutState.Set &&
                (exerciseId == null || state.exerciseId == exerciseId) &&
                (setIndex == null || state.setIndex == setIndex)
        }
        if (genericSetFallback != null) return genericSetFallback

        return firstMatching { _ -> true }
    }
}
