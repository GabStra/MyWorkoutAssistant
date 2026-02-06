package com.gabstra.myworkoutassistant.shared.utils

import com.gabstra.myworkoutassistant.shared.workout.state.CalibrationContext
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState

object CalibrationHelper {
    /**
     * Calculates the weight adjustment multiplier based on calibration set RIR.
     * 
     * @param rir Reps in Reserve from calibration set
     * @param formBreaks Whether form broke during the set
     * @return Multiplier to apply to calibration weight (e.g., 1.10 for +10%, 0.95 for -5%)
     */
    fun calculateWeightAdjustment(rir: Double, formBreaks: Boolean = false): Double {
        // Handle form breaks or negative RIR as RIR 0 / form breaks
        if (formBreaks || rir < 0) {
            // RIR 0 / form breaks → subtract 5-10% (use 7.5% as middle)
            return 0.925 // 1.0 - 0.075 = 0.925
        }
        
        return when {
            rir >= 5.0 -> {
                // RIR 5+ → add 10%
                1.10
            }
            rir >= 4.0 -> {
                // RIR 4 → add 5%
                1.05
            }
            rir >= 3.0 -> {
                // RIR 3 → add 2.5%
                1.025
            }
            rir >= 2.0 -> {
                // RIR 2 → keep (no adjustment)
                1.0
            }
            rir >= 1.0 -> {
                // RIR 1 → subtract 2.5-5% (use 3.75% as middle)
                0.9625 // 1.0 - 0.0375 = 0.9625
            }
            else -> {
                // RIR 0 → subtract 5-10% (use 7.5% as middle)
                0.925 // 1.0 - 0.075 = 0.925
            }
        }
    }
    
    /**
     * Applies calibration adjustment to calculate the adjusted weight for work sets.
     * 
     * @param calibrationWeight The weight used in the calibration set
     * @param calibrationRIR The RIR rating from the calibration set
     * @param formBreaks Whether form broke during the calibration set
     * @return The adjusted weight to use for work sets
     */
    fun applyCalibrationAdjustment(
        calibrationWeight: Double,
        calibrationRIR: Double,
        formBreaks: Boolean = false
    ): Double {
        val multiplier = calculateWeightAdjustment(calibrationRIR, formBreaks)
        return calibrationWeight * multiplier
    }

    /**
     * Returns true when the given set is a work set whose weight should be shown as "Pending"
     * because calibration is not yet complete. Uses [CalibrationContext] when provided so no
     * scanning of [allWorkoutStates] is needed.
     *
     * @param setState The set state for the row being rendered
     * @param calibrationContext Current calibration context from the ViewModel, or null to use fallback
     * @param isCalibrationEnabled Whether the exercise requires load calibration
     * @param isWarmupSet Whether the row's set is a warmup set
     * @param isCalibrationSet Whether the row's set is the calibration set (by subCategory)
     * @param isFutureExercise Whether this exercise has not been reached yet in the workout
     * @return true if work set weight should display "Pending"
     */
    fun isPendingCalibration(
        setState: WorkoutState.Set,
        calibrationContext: CalibrationContext?,
        isCalibrationEnabled: Boolean,
        isWarmupSet: Boolean,
        isCalibrationSet: Boolean,
        isFutureExercise: Boolean
    ): Boolean {
        if (!isCalibrationEnabled || isWarmupSet || isCalibrationSet || setState.isCalibrationSet) return false
        if (calibrationContext != null) {
            return isFutureExercise || calibrationContext.exerciseId == setState.exerciseId
        }
        return isFutureExercise
    }

    /**
     * Returns true when the given set is a work set whose weight should be shown as "Pending"
     * because calibration is not yet complete. Scans [allWorkoutStates]; prefer
     * [isPendingCalibration(setState, calibrationContext, ...)] when context is available.
     *
     * @param currentWorkoutState The current workout state from the state machine
     * @param allWorkoutStates The full ordered list of workout states
     * @param setState The set state for the row being rendered
     * @param isCalibrationEnabled Whether the exercise requires load calibration
     * @param isWarmupSet Whether the row's set is a warmup set
     * @param isCalibrationSet Whether the row's set is the calibration set (by subCategory)
     * @param isFutureExercise Whether this exercise has not been reached yet in the workout
     * @return true if work set weight should display "Pending"
     */
    fun isPendingCalibration(
        currentWorkoutState: WorkoutState,
        allWorkoutStates: List<WorkoutState>,
        setState: WorkoutState.Set,
        isCalibrationEnabled: Boolean,
        isWarmupSet: Boolean,
        isCalibrationSet: Boolean,
        isFutureExercise: Boolean
    ): Boolean {
        val hasCalibrationRIRSelection = (currentWorkoutState is WorkoutState.CalibrationRIRSelection &&
            (currentWorkoutState as WorkoutState.CalibrationRIRSelection).exerciseId == setState.exerciseId) ||
            allWorkoutStates.any { state ->
                state is WorkoutState.CalibrationRIRSelection && state.exerciseId == setState.exerciseId
            }
        val hasCalibrationLoadSelection = (currentWorkoutState is WorkoutState.CalibrationLoadSelection &&
            (currentWorkoutState as WorkoutState.CalibrationLoadSelection).exerciseId == setState.exerciseId) ||
            allWorkoutStates.any { state ->
                state is WorkoutState.CalibrationLoadSelection && state.exerciseId == setState.exerciseId
            }
        val isOnCalibrationSet = currentWorkoutState is WorkoutState.Set &&
            (currentWorkoutState as WorkoutState.Set).exerciseId == setState.exerciseId &&
            (currentWorkoutState as WorkoutState.Set).isCalibrationSet
        val calibrationIndex = allWorkoutStates.indexOfFirst { state ->
            state is WorkoutState.Set &&
                (state as WorkoutState.Set).exerciseId == setState.exerciseId &&
                (state as WorkoutState.Set).isCalibrationSet
        }
        val currentIndex = allWorkoutStates.indexOf(currentWorkoutState)
        val isOnWarmupBeforeCalibration = currentWorkoutState is WorkoutState.Set &&
            (currentWorkoutState as WorkoutState.Set).exerciseId == setState.exerciseId &&
            (currentWorkoutState as WorkoutState.Set).isWarmupSet &&
            calibrationIndex >= 0 &&
            currentIndex >= 0 &&
            currentIndex <= calibrationIndex

        return isCalibrationEnabled &&
            !isWarmupSet &&
            !isCalibrationSet &&
            !setState.isCalibrationSet &&
            (hasCalibrationRIRSelection || isOnCalibrationSet || isOnWarmupBeforeCalibration || hasCalibrationLoadSelection || isFutureExercise)
    }
}

