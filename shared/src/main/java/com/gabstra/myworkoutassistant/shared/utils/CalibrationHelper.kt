package com.gabstra.myworkoutassistant.shared.utils

import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import java.util.UUID

object CalibrationHelper {
    fun isWarmupSet(set: Set): Boolean = when (set) {
        is BodyWeightSet -> set.subCategory == SetSubCategory.WarmupSet
        is WeightSet -> set.subCategory == SetSubCategory.WarmupSet
        else -> false
    }

    fun isCalibrationSetBySubCategory(set: Set): Boolean = when (set) {
        is BodyWeightSet -> set.subCategory == SetSubCategory.CalibrationSet
        is WeightSet -> set.subCategory == SetSubCategory.CalibrationSet
        else -> false
    }

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

    fun shouldShowPendingCalibrationForWorkSet(
        setState: WorkoutState.Set,
        isCalibrationEnabled: Boolean,
        isWarmupSet: Boolean,
        isCalibrationSetBySubCategory: Boolean,
        hasUnconfirmedLoadSelectionForExercise: Boolean = false
    ): Boolean {
        return isCalibrationEnabled &&
            !isWarmupSet &&
            !isCalibrationSetBySubCategory &&
            !setState.isCalibrationSet &&
            hasUnconfirmedLoadSelectionForExercise
    }

    fun shouldHideCalibrationExecutionWeight(
        setState: WorkoutState.Set,
        isCalibrationSetBySubCategory: Boolean,
        hasUnconfirmedLoadSelectionForExercise: Boolean = false
    ): Boolean = isCalibrationSetBySubCategory &&
        setState.isCalibrationSet &&
        hasUnconfirmedLoadSelectionForExercise

    fun hasUnconfirmedLoadSelectionForExercise(
        allWorkoutStates: List<WorkoutState>,
        exerciseId: UUID
    ): Boolean = allWorkoutStates.any { state ->
        state is WorkoutState.CalibrationLoadSelection &&
            state.exerciseId == exerciseId &&
            !state.isLoadConfirmed
    }
}

