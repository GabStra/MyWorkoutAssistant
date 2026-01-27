package com.gabstra.myworkoutassistant.shared.viewmodels

import androidx.lifecycle.viewModelScope
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.utils.CalibrationHelper
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.LocalDateTime
import java.util.UUID

/**
 * Extensions implementing [WorkoutViewModel.applyCalibrationRIR] and its helpers.
 * Kept in a separate file to reduce WorkoutViewModel size and improve readability.
 */

private fun WorkoutViewModel.storeRIRInCalibrationSetData(
    currentState: WorkoutState.CalibrationRIRSelection,
    rir: Double
) {
    val currentSetData = currentState.currentSetData
    val updatedSetData = when (currentSetData) {
        is WeightSetData -> currentSetData.copy(calibrationRIR = rir)
        is BodyWeightSetData -> currentSetData.copy(calibrationRIR = rir)
        else -> currentSetData
    }
    currentState.currentSetData = updatedSetData
}

private fun WorkoutViewModel.extractCalibrationWeight(
    currentSetData: com.gabstra.myworkoutassistant.shared.setdata.SetData
): Double {
    return when (currentSetData) {
        is WeightSetData -> currentSetData.actualWeight
        is BodyWeightSetData -> currentSetData.additionalWeight
        else -> 0.0
    }
}

private fun WorkoutViewModel.roundToNearestAvailableWeight(
    weight: Double,
    availableWeights: kotlin.collections.Set<Double>
): Double {
    return if (availableWeights.isNotEmpty()) {
        availableWeights.minByOrNull { kotlin.math.abs(it - weight) } ?: weight
    } else {
        weight
    }
}

private fun WorkoutViewModel.updateWorkSetsInExercise(
    exercise: Exercise,
    adjustedWeight: Double,
    availableWeights: kotlin.collections.Set<Double>
): Pair<List<Set>, Map<UUID, Set>> {
    val updatedSets = exercise.sets.toMutableList()
    val setUpdates = mutableMapOf<UUID, Set>()
    
    for (i in exercise.sets.indices) {
        val set = exercise.sets[i]
        when {
            set is RestSet -> continue
            set is WeightSet && set.subCategory == SetSubCategory.WorkSet -> {
                val roundedWeight = roundToNearestAvailableWeight(adjustedWeight, availableWeights)
                val updatedSet = set.copy(weight = roundedWeight)
                updatedSets[i] = updatedSet
                setUpdates[set.id] = updatedSet
            }
            set is BodyWeightSet && set.subCategory == SetSubCategory.WorkSet -> {
                val roundedWeight = roundToNearestAvailableWeight(adjustedWeight, availableWeights)
                val updatedSet = set.copy(additionalWeight = roundedWeight)
                updatedSets[i] = updatedSet
                setUpdates[set.id] = updatedSet
            }
        }
    }
    
    return Pair(updatedSets, setUpdates)
}

private fun WorkoutViewModel.updateWorkSetStateData(
    state: WorkoutState.Set,
    updatedSet: Set
): com.gabstra.myworkoutassistant.shared.setdata.SetData {
    return when (val setData = state.currentSetData) {
        is WeightSetData -> {
            val weightSet = updatedSet as? WeightSet
            if (weightSet != null) {
                val newData = setData.copy(actualWeight = weightSet.weight)
                newData.copy(volume = newData.calculateVolume())
            } else {
                setData
            }
        }
        is BodyWeightSetData -> {
            val bodyWeightSet = updatedSet as? BodyWeightSet
            if (bodyWeightSet != null) {
                val newData = setData.copy(additionalWeight = bodyWeightSet.additionalWeight)
                newData.copy(volume = newData.calculateVolume())
            } else {
                setData
            }
        }
        else -> setData
    }
}

private fun WorkoutViewModel.updateCalibrationSetPreviousData(
    state: WorkoutState.Set
): com.gabstra.myworkoutassistant.shared.setdata.SetData? {
    val updatedSetData = state.currentSetData
    return when {
        updatedSetData is WeightSetData && 
        state.previousSetData is WeightSetData -> {
            val prevData = state.previousSetData as WeightSetData
            val newPrevData = prevData.copy(actualWeight = updatedSetData.actualWeight)
            newPrevData.copy(volume = newPrevData.calculateVolume())
        }
        updatedSetData is BodyWeightSetData && 
        state.previousSetData is BodyWeightSetData -> {
            val prevData = state.previousSetData as BodyWeightSetData
            val newPrevData = prevData.copy(additionalWeight = updatedSetData.additionalWeight)
            newPrevData.copy(volume = newPrevData.calculateVolume())
        }
        else -> null
    }
}

private fun WorkoutViewModel.findCalibrationSetExecutionState(
    machine: WorkoutStateMachine,
    exerciseId: UUID
): Pair<WorkoutState.Set?, Int> {
    val calibrationSetExecutionState = machine.allStates.find { 
        it is WorkoutState.Set && (it as WorkoutState.Set).isCalibrationSet && (it as WorkoutState.Set).exerciseId == exerciseId
    } as? WorkoutState.Set
    val calibrationSetIndex = if (calibrationSetExecutionState != null) {
        machine.allStates.indexOf(calibrationSetExecutionState)
    } else {
        -1
    }
    return Pair(calibrationSetExecutionState, calibrationSetIndex)
}

private fun WorkoutViewModel.updateWorkSetStates(
    statesWithoutRIR: MutableList<WorkoutState>,
    currentState: WorkoutState.CalibrationRIRSelection,
    setUpdates: Map<UUID, Set>
) {
    for (state in statesWithoutRIR) {
        if (state is WorkoutState.Set && state.exerciseId == currentState.exerciseId) {
            val updatedSet = setUpdates[state.set.id]
            if (updatedSet != null && !state.isCalibrationSet) {
                // Work set: directly mutate set and currentSetData, leave previousSetData unchanged
                state.set = updatedSet
                state.currentSetData = updateWorkSetStateData(state, updatedSet)
                // Do NOT touch previousSetData - leave it as load-selection weight
            } else if (state.isCalibrationSet) {
                // Calibration set: update previousSetData to match currentSetData
                val updatedPreviousSetData = updateCalibrationSetPreviousData(state)
                if (updatedPreviousSetData != null) {
                    val calibrationStateIndex = statesWithoutRIR.indexOf(state)
                    if (calibrationStateIndex >= 0) {
                        statesWithoutRIR[calibrationStateIndex] = state.copy(previousSetData = updatedPreviousSetData)
                    }
                }
            }
        }
    }
}

private fun WorkoutViewModel.calculateNewCurrentIndex(
    calibrationSetIndex: Int,
    currentIndex: Int,
    finalUpdatedStates: List<WorkoutState>
): Int {
    return if (calibrationSetIndex >= 0 && calibrationSetIndex < finalUpdatedStates.size - 1) {
        calibrationSetIndex + 1
    } else if (currentIndex < finalUpdatedStates.size) {
        currentIndex
    } else {
        finalUpdatedStates.size - 1
    }
}

private fun WorkoutViewModel.triggerPlateRecalculationIfNeeded(
    finalUpdatedStates: List<WorkoutState>,
    newCurrentIndex: Int,
    currentState: WorkoutState.CalibrationRIRSelection,
    exercise: Exercise,
    equipment: WeightLoadedEquipment?
) {
    val firstWorkSetState = finalUpdatedStates.getOrNull(newCurrentIndex) as? WorkoutState.Set
    if (firstWorkSetState != null && 
        firstWorkSetState.exerciseId == currentState.exerciseId &&
        equipment is Barbell && 
        (exercise.exerciseType == ExerciseType.WEIGHT || exercise.exerciseType == ExerciseType.BODY_WEIGHT)) {
        val totalWeight = when (val set = firstWorkSetState.set) {
            is WeightSet -> set.weight
            is BodyWeightSet -> {
                val relativeBodyWeight = bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
                relativeBodyWeight + set.additionalWeight
            }
            else -> null
        }
        if (totalWeight != null) {
            schedulePlateRecalculation(totalWeight)
        }
    }
}

fun WorkoutViewModel.applyCalibrationRIR(rir: Double, formBreaks: Boolean = false) {
    val machine = stateMachine ?: return
    val currentState = machine.currentState as? WorkoutState.CalibrationRIRSelection ?: return
    
    viewModelScope.launch(dispatchers.io) {
        // Store RIR in calibration set's SetData
        storeRIRInCalibrationSetData(currentState, rir)
        
        // Get calibration weight
        val currentSetData = currentState.currentSetData
        val calibrationWeight = extractCalibrationWeight(currentSetData)
        
        // Calculate adjusted weight
        val adjustedWeight = CalibrationHelper.applyCalibrationAdjustment(calibrationWeight, rir, formBreaks)
        
        // Find all remaining work sets in the exercise
        val exercise = exercisesById[currentState.exerciseId] ?: return@launch
        val equipment = currentState.equipment
        val availableWeights = getWeightByEquipment(equipment)
        
        // Update all work sets in the exercise
        // Note: The calibration set may have already been removed from the exercise's sets list,
        // so we update all work sets regardless of calibration set position
        val (updatedSets, setUpdates) = updateWorkSetsInExercise(exercise, adjustedWeight, availableWeights)
        
        // Update exercise with adjusted sets and disable calibration requirement
        // since calibration has been completed
        val updatedExercise = exercise.copy(
            sets = updatedSets,
            requiresLoadCalibration = false
        )
        updateWorkout(exercise, updatedExercise)
        
        // Update states in state machine to reflect new set weights and remove CalibrationRIRSelection
        withContext(dispatchers.main) {
            // Update exercisesById map to keep it in sync with the updated workout
            initializeExercisesMaps(selectedWorkout.value)
            
            val machine = stateMachine ?: return@withContext
            val currentIndex = machine.currentIndex
            
            // Store calibration Set execution state index before removing CalibrationRIRSelection
            val (calibrationSetExecutionState, calibrationSetIndex) = findCalibrationSetExecutionState(
                machine, currentState.exerciseId
            )
            
            // Remove CalibrationRIRSelection state and move to next state
            val statesWithoutRIR = machine.allStates.toMutableList()
            statesWithoutRIR.removeAt(currentIndex)
            
            // Update work set states: directly mutate in place instead of mapping
            updateWorkSetStates(statesWithoutRIR, currentState, setUpdates)
            
            val finalUpdatedStates = statesWithoutRIR
            
            // Store the calibration set with RIR in executedSetsHistory before removing CalibrationRIRSelection
            if (calibrationSetIndex >= 0 && calibrationSetExecutionState != null) {
                // Temporarily set current state to calibration Set execution to store it
                stateMachine = WorkoutStateMachine(machine.allStates, calibrationSetIndex) { LocalDateTime.now() }
                storeSetData()
            }
            
            // Adjust current index if we removed CalibrationRIRSelection
            // If we were at CalibrationRIRSelection, move to next state after calibration Set execution
            val newCurrentIndex = calculateNewCurrentIndex(calibrationSetIndex, currentIndex, finalUpdatedStates)
            
            stateMachine = WorkoutStateMachine(finalUpdatedStates, newCurrentIndex) { LocalDateTime.now() }
            updateStateFlowsFromMachine()
            
            // Trigger plate recalculation for the first work set after RIR
            triggerPlateRecalculationIfNeeded(
                finalUpdatedStates, newCurrentIndex, currentState, exercise, equipment
            )
        }
    }
}
