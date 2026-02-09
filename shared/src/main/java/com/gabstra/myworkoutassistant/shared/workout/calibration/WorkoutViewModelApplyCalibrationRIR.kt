package com.gabstra.myworkoutassistant.shared.workout.calibration

import androidx.compose.runtime.mutableStateOf
import androidx.lifecycle.viewModelScope
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.initializeSetData
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
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import com.gabstra.myworkoutassistant.shared.workout.state.ExerciseChildItem
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateContainer
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateEditor
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateMachine
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateQueries
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateSequenceItem
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateSequenceOps
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
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
    val calibrationSetExecutionState = machine.allStates
        .filterIsInstance<WorkoutState.Set>()
        .firstOrNull {
            it.isCalibrationSet && WorkoutStateQueries.stateExerciseId(it) == exerciseId
        }
    val calibrationSetIndex = if (calibrationSetExecutionState != null) {
        machine.allStates.indexOf(calibrationSetExecutionState)
    } else {
        -1
    }
    return Pair(calibrationSetExecutionState, calibrationSetIndex)
}

private fun WorkoutViewModel.updateWorkSetStatesInList(
    states: MutableList<WorkoutState>,
    currentState: WorkoutState.CalibrationRIRSelection,
    setUpdates: Map<UUID, Set>
) {
    for (i in states.indices) {
        val state = states[i]
        if (state is WorkoutState.Set && WorkoutStateQueries.stateExerciseId(state) == currentState.exerciseId) {
            val updatedSet = setUpdates[WorkoutStateQueries.stateSetId(state)]
            if (updatedSet != null && !state.isCalibrationSet) {
                // Work set: update set and currentSetData to adjusted load; set previousSetData to same so UI shows neutral color
                val newSetData = updateWorkSetStateData(state, updatedSet)
                state.set = updatedSet
                state.currentSetData = newSetData
                states[i] = state.copy(previousSetData = newSetData)
            } else if (state.isCalibrationSet) {
                // Calibration set: update previousSetData to match currentSetData
                val updatedPreviousSetData = updateCalibrationSetPreviousData(state)
                if (updatedPreviousSetData != null) {
                    states[i] = state.copy(previousSetData = updatedPreviousSetData)
                }
            }
        }
    }
}

private fun WorkoutViewModel.applyWorkSetUpdateToState(
    state: WorkoutState,
    currentState: WorkoutState.CalibrationRIRSelection,
    setUpdates: Map<UUID, Set>
): WorkoutState {
    if (state !is WorkoutState.Set) return state
    if (WorkoutStateQueries.stateExerciseId(state) != currentState.exerciseId) return state

    val updatedSet = setUpdates[WorkoutStateQueries.stateSetId(state)]
    return if (updatedSet != null && !state.isCalibrationSet) {
        // Work set: keep Set object and SetData aligned with adjusted load.
        val newSetData = updateWorkSetStateData(state, updatedSet)
        state.set = updatedSet
        state.currentSetData = newSetData
        state.copy(previousSetData = newSetData)
    } else if (state.isCalibrationSet) {
        // Calibration execution set: keep previous data aligned with executed data after RIR capture.
        val updatedPreviousSetData = updateCalibrationSetPreviousData(state)
        if (updatedPreviousSetData != null) {
            state.copy(previousSetData = updatedPreviousSetData)
        } else {
            state
        }
    } else {
        state
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

private fun WorkoutViewModel.createPostCalibrationRestState(
    calibrationSetState: WorkoutState.Set
): WorkoutState.Rest {
    val restSet = RestSet(UUID.randomUUID(), 60)
    return WorkoutState.Rest(
        set = restSet,
        order = calibrationSetState.setIndex + 1u,
        currentSetDataState = mutableStateOf(initializeSetData(restSet)),
        exerciseId = calibrationSetState.exerciseId
    )
}

private fun WorkoutViewModel.ensurePostCalibrationRestState(
    states: MutableList<WorkoutState>,
    exerciseId: UUID
) {
    val calibrationSetIndex = states.indexOfFirst {
        it is WorkoutState.Set &&
            it.isCalibrationSet &&
            WorkoutStateQueries.stateExerciseId(it) == exerciseId
    }
    if (calibrationSetIndex < 0) return

    val nextState = states.getOrNull(calibrationSetIndex + 1)
    if (nextState is WorkoutState.Rest) return

    val calibrationSetState = states[calibrationSetIndex] as? WorkoutState.Set ?: return
    states.add(calibrationSetIndex + 1, createPostCalibrationRestState(calibrationSetState))
}

fun WorkoutViewModel.applyCalibrationRIR(rir: Double, formBreaks: Boolean = false) {
    val machine = stateMachine ?: return
    val currentState = machine.currentState as? WorkoutState.CalibrationRIRSelection ?: return
    
    launchIO {
        // Store RIR in calibration set's SetData
        storeRIRInCalibrationSetData(currentState, rir)
        
        // Get calibration weight
        val currentSetData = currentState.currentSetData
        val calibrationWeight = extractCalibrationWeight(currentSetData)
        
        // Calculate adjusted weight
        val adjustedWeight = CalibrationHelper.applyCalibrationAdjustment(calibrationWeight, rir, formBreaks)
        
        // Find all remaining work sets in the exercise
        val exercise = exercisesById[currentState.exerciseId] ?: return@launchIO
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

            // Use calibration context for index; fallback to search if context missing (e.g. migration)
            val calibrationSetIndex = getCalibrationContextValue()?.calibrationSetExecutionStateIndex
                ?: findCalibrationSetExecutionState(machine, currentState.exerciseId).second
            val calibrationSetExecutionState = if (calibrationSetIndex >= 0 && calibrationSetIndex < machine.allStates.size) {
                machine.allStates[calibrationSetIndex] as? WorkoutState.Set
            } else null

            // Store the calibration set with RIR in executedSetsHistory before removing CalibrationRIRSelection
            if (calibrationSetIndex >= 0 && calibrationSetExecutionState != null) {
                // Temporarily set current state to calibration Set execution to store it
                val tempMachine = machine.withCurrentIndex(calibrationSetIndex)
                stateMachine = tempMachine
                storeSetData()
            }
            
            // Remove CalibrationRIRSelection from sequence (from CalibrationExecutionBlock for ExerciseState)
            val updatedMachine = machine.editSequence(transform = { sequence ->
                sequence.map { item ->
                    when (item) {
                        is WorkoutStateSequenceItem.Container -> {
                            when (val container = item.container) {
                                is WorkoutStateContainer.ExerciseState -> {
                                    if (container.exerciseId == currentState.exerciseId) {
                                        val updatedChildItems = container.childItems.map { childItem ->
                                            when (childItem) {
                                                is ExerciseChildItem.Normal -> childItem
                                                is ExerciseChildItem.CalibrationExecutionBlock -> {
                                                    val newList = childItem.childStates
                                                        .filterNot { it is WorkoutState.CalibrationRIRSelection }
                                                        .toMutableList()
                                                    updateWorkSetStatesInList(newList, currentState, setUpdates)
                                                    ensurePostCalibrationRestState(newList, currentState.exerciseId)
                                                    ExerciseChildItem.CalibrationExecutionBlock(newList)
                                                }
                                                is ExerciseChildItem.LoadSelectionBlock -> childItem
                                                is ExerciseChildItem.UnilateralSetBlock -> childItem
                                            }
                                        }.toMutableList()
                                        WorkoutStateSequenceItem.Container(container.copy(childItems = updatedChildItems))
                                    } else {
                                        item
                                    }
                                }
                                is WorkoutStateContainer.SupersetState -> {
                                    val updatedChildStates = container.childStates
                                        .filterNot { it is WorkoutState.CalibrationRIRSelection }
                                        .toMutableList()
                                    updateWorkSetStatesInList(updatedChildStates, currentState, setUpdates)
                                    ensurePostCalibrationRestState(updatedChildStates, currentState.exerciseId)
                                    WorkoutStateSequenceItem.Container(container.copy(childStates = updatedChildStates))
                                }
                            }
                        }
                        is WorkoutStateSequenceItem.RestBetweenExercises -> item
                    }
                }
            })
            
            val fullyUpdatedMachine = updatedMachine.editSequence(transform = { sequence ->
                WorkoutStateSequenceOps.mapSequenceStates(sequence) { state ->
                    applyWorkSetUpdateToState(state, currentState, setUpdates)
                }
            })

            // Adjust current index if we removed CalibrationRIRSelection
            // If we were at CalibrationRIRSelection, move to next state after calibration Set execution
            val newCurrentIndex = calculateNewCurrentIndex(calibrationSetIndex, currentIndex, fullyUpdatedMachine.allStates)
            
            stateMachine = fullyUpdatedMachine.withCurrentIndex(newCurrentIndex)
            populateNextStateSets()
            updateStateFlowsFromMachine()
            
            // Recalculate plate configs for all work sets (current state is Rest so schedulePlateRecalculation would no-op)
            if (equipment is Barbell &&
                (exercise.exerciseType == ExerciseType.WEIGHT || exercise.exerciseType == ExerciseType.BODY_WEIGHT)) {
                val firstWorkSetStateIndex = calibrationSetIndex + 2
                val machine = stateMachine ?: return@withContext
                val allStates = machine.allStates
                if (firstWorkSetStateIndex < allStates.size) {
                    val remainingStates = WorkoutStateQueries.remainingSetStatesForExercise(
                        machine = machine,
                        fromIndexInclusive = firstWorkSetStateIndex,
                        exerciseId = currentState.exerciseId
                    )
                    val weights = remainingStates.map { state ->
                        when (val set = state.set) {
                            is WeightSet -> set.weight
                            is BodyWeightSet -> {
                                val relativeBodyWeight = bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
                                relativeBodyWeight + set.additionalWeight
                            }
                            else -> 0.0
                        }
                    }
                    if (weights.size == remainingStates.size) {
                        recalculatePlatesForExerciseFromIndex(
                            currentState.exerciseId,
                            firstWorkSetStateIndex,
                            weights,
                            equipment
                        )
                        // Repopulate Rest.nextState so the Rest screen shows plate changes for the updated load
                        stateMachine?.let { m -> populateNextStateForRest(m) }
                        updateStateFlowsFromMachine()
                    }
                }
            }
        }
    }
}

