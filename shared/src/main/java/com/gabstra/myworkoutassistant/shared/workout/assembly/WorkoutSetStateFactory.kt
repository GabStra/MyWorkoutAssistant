package com.gabstra.myworkoutassistant.shared.workout.assembly

import androidx.compose.runtime.mutableStateOf
import com.gabstra.myworkoutassistant.shared.ExerciseInfo
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.initializeSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.utils.PlateCalculator
import com.gabstra.myworkoutassistant.shared.workout.state.ExerciseChildItem
import com.gabstra.myworkoutassistant.shared.workout.state.ProgressionState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.util.UUID

class WorkoutSetStateFactory {
    fun isWarmupSet(set: Set): Boolean = when (set) {
        is BodyWeightSet -> set.subCategory == SetSubCategory.WarmupSet
        is WeightSet -> set.subCategory == SetSubCategory.WarmupSet
        else -> false
    }

    fun isCalibrationSet(set: Set): Boolean = when (set) {
        is BodyWeightSet -> set.subCategory == SetSubCategory.CalibrationSet
        is WeightSet -> set.subCategory == SetSubCategory.CalibrationSet
        else -> false
    }

    fun isUnilateralExercise(exercise: Exercise): Boolean {
        val rest = exercise.intraSetRestInSeconds
        return rest != null && rest > 0
    }

    fun buildCalibrationLoadSelectionState(
        exercise: Exercise,
        set: Set,
        setIndex: Int,
        previousSetData: SetData?,
        currentSetData: SetData,
        bodyWeightKg: Double,
        isUnilateral: Boolean,
        getEquipmentById: (UUID) -> WeightLoadedEquipment?
    ): WorkoutState.CalibrationLoadSelection {
        return WorkoutState.CalibrationLoadSelection(
            exerciseId = exercise.id,
            calibrationSet = set,
            setIndex = setIndex.toUInt(),
            previousSetData = previousSetData,
            currentSetDataState = mutableStateOf(currentSetData),
            equipment = exercise.equipmentId?.let { getEquipmentById(it) },
            lowerBoundMaxHRPercent = exercise.lowerBoundMaxHRPercent,
            upperBoundMaxHRPercent = exercise.upperBoundMaxHRPercent,
            currentBodyWeight = bodyWeightKg,
            isUnilateral = isUnilateral
        )
    }

    fun buildWorkoutSetState(
        exercise: Exercise,
        set: Set,
        setIndex: Int,
        previousSetData: SetData?,
        currentSetData: SetData,
        historySet: SetHistory?,
        plateChangeResult: PlateCalculator.Companion.PlateChangeResult?,
        exerciseInfo: ExerciseInfo?,
        progressionState: ProgressionState?,
        isWarmupSet: Boolean,
        bodyWeightKg: Double,
        isUnilateral: Boolean,
        isCalibrationSet: Boolean,
        getEquipmentById: (UUID) -> WeightLoadedEquipment?
    ): WorkoutState.Set {
        return WorkoutState.Set(
            exercise.id,
            set,
            setIndex.toUInt(),
            previousSetData,
            currentSetDataState = mutableStateOf(currentSetData),
            hasNoHistory = historySet == null,
            startTime = null,
            skipped = false,
            lowerBoundMaxHRPercent = exercise.lowerBoundMaxHRPercent,
            upperBoundMaxHRPercent = exercise.upperBoundMaxHRPercent,
            currentBodyWeight = bodyWeightKg,
            plateChangeResult = plateChangeResult,
            streak = exerciseInfo?.successfulSessionCounter?.toInt() ?: 0,
            progressionState = progressionState,
            isWarmupSet = isWarmupSet,
            equipment = exercise.equipmentId?.let { getEquipmentById(it) },
            isUnilateral = isUnilateral,
            isCalibrationSet = isCalibrationSet
        )
    }

    fun buildUnilateralSetBlock(
        exercise: Exercise,
        setState: WorkoutState.Set,
        setIndex: Int
    ): ExerciseChildItem.UnilateralSetBlock? {
        val restDuration = exercise.intraSetRestInSeconds ?: return null
        val restSet = RestSet(UUID.randomUUID(), restDuration)
        val restState = WorkoutState.Rest(
            set = restSet,
            order = setIndex.toUInt(),
            currentSetDataState = mutableStateOf(initializeSetData(restSet)),
            nextState = setState,
            exerciseId = exercise.id,
            isIntraSetRest = true
        )
        val updatedSetState = setState.copy(isUnilateral = true, intraSetTotal = 2u, intraSetCounter = 1u)
        return ExerciseChildItem.UnilateralSetBlock(
            mutableListOf(updatedSetState, restState, updatedSetState)
        )
    }
}


