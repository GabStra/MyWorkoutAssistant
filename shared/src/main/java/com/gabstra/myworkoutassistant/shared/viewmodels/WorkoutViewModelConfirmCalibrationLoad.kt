package com.gabstra.myworkoutassistant.shared.viewmodels

import android.util.Log
import androidx.compose.runtime.mutableStateOf
import androidx.lifecycle.viewModelScope
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.copySetData
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
import com.gabstra.myworkoutassistant.shared.utils.WarmupPlanner
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.LocalDateTime
import java.util.UUID

/**
 * Extensions implementing [WorkoutViewModel.confirmCalibrationLoad] and its helpers.
 * Kept in a separate file to reduce WorkoutViewModel size and improve readability.
 */

private fun WorkoutViewModel.extractSelectedWeight(currentState: WorkoutState.CalibrationLoadSelection): Double? {
    return when (val setData = currentState.currentSetData) {
        is WeightSetData -> setData.actualWeight
        is BodyWeightSetData -> setData.additionalWeight
        else -> null
    }
}

private fun WorkoutViewModel.updateCalibrationSetWithWeight(
    currentState: WorkoutState.CalibrationLoadSelection,
    selectedWeight: Double
): Set? {
    return when (val set = currentState.calibrationSet) {
        is WeightSet -> set.copy(weight = selectedWeight)
        is BodyWeightSet -> set.copy(additionalWeight = selectedWeight)
        else -> null
    }
}

private fun WorkoutViewModel.calculateWorkWeightTotal(
    exercise: Exercise,
    selectedWeight: Double
): Double? {
    return when (exercise.exerciseType) {
        ExerciseType.BODY_WEIGHT -> {
            val relativeBodyWeight = bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
            relativeBodyWeight + selectedWeight
        }
        ExerciseType.WEIGHT -> selectedWeight
        else -> null
    }
}

private fun WorkoutViewModel.getAvailableTotalsForWarmups(
    exercise: Exercise,
    equipment: WeightLoadedEquipment
): kotlin.collections.Set<Double> {
    return when (exercise.exerciseType) {
        ExerciseType.WEIGHT -> getCachedAvailableTotals(equipment)
        ExerciseType.BODY_WEIGHT -> {
            val relativeBodyWeight = bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
            val extraTotals = getCachedAvailableTotals(equipment)
            extraTotals.map { relativeBodyWeight + it }.toSet() + setOf(relativeBodyWeight)
        }
        else -> emptySet()
    }
}

private fun WorkoutViewModel.toSetInternalWeight(
    exercise: Exercise,
    desiredTotal: Double
): Double {
    return when (exercise.exerciseType) {
        ExerciseType.BODY_WEIGHT -> {
            val relativeBodyWeight = bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
            desiredTotal - relativeBodyWeight
        }
        ExerciseType.WEIGHT -> desiredTotal
        else -> 0.0
    }
}

private suspend fun WorkoutViewModel.generateWarmupStates(
    exercise: Exercise,
    equipment: WeightLoadedEquipment?,
    currentState: WorkoutState.CalibrationLoadSelection,
    selectedWeight: Double
): List<WorkoutState> {
    if (!exercise.generateWarmUpSets || equipment == null ||
        (exercise.exerciseType != ExerciseType.BODY_WEIGHT && exercise.exerciseType != ExerciseType.WEIGHT)
    ) {
        return emptyList()
    }
    val workWeightTotal = calculateWorkWeightTotal(exercise, selectedWeight) ?: return emptyList()
    val workReps = when (val set = currentState.calibrationSet) {
        is WeightSet -> set.reps
        is BodyWeightSet -> set.reps
        else -> return emptyList()
    }
    val availableTotals = getAvailableTotalsForWarmups(exercise, equipment)
    // For calibration, we don't have prior exercises context, so pass empty list
    val priorExercises = emptyList<Exercise>()
    val warmups: List<Pair<Double, Int>> = if (equipment is Barbell && exercise.exerciseType == ExerciseType.WEIGHT) {
        WarmupPlanner.buildWarmupSetsForBarbell(
            availableTotals = availableTotals,
            workWeight = workWeightTotal,
            workReps = workReps,
            barbell = equipment,
            exercise = exercise,
            priorExercises = priorExercises,
            initialSetup = emptyList(),
            maxWarmups = 4
        )
    } else {
        WarmupPlanner.buildWarmupSets(
            availableTotals = availableTotals,
            workWeight = workWeightTotal,
            workReps = workReps,
            exercise = exercise,
            priorExercises = priorExercises,
            equipment = equipment,
            maxWarmups = 4
        )
    }
    val exerciseInfo = withContext(dispatchers.io) { exerciseInfoDao.getExerciseInfoById(exercise.id) }
    val progressionData = exerciseProgressionByExerciseId[exercise.id]
    val progressionState = progressionData?.second
    val warmupStates = mutableListOf<WorkoutState>()
    val relativeBodyWeight = if (exercise.exerciseType == ExerciseType.BODY_WEIGHT) {
        bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
    } else {
        0.0
    }
    warmups.forEachIndexed { warmupIndex, (total, reps) ->
        val internalWeight = toSetInternalWeight(exercise, total)
        val warmupSet: Set = when (exercise.exerciseType) {
            ExerciseType.BODY_WEIGHT -> BodyWeightSet(
                UUID.randomUUID(), reps, internalWeight, subCategory = SetSubCategory.WarmupSet
            )
            ExerciseType.WEIGHT -> WeightSet(
                UUID.randomUUID(), reps, internalWeight, subCategory = SetSubCategory.WarmupSet
            )
            else -> return emptyList()
        }
        var warmupSetData = initializeSetData(warmupSet)
        if (warmupSetData is BodyWeightSetData) {
            warmupSetData = warmupSetData.copy(relativeBodyWeightInKg = relativeBodyWeight)
            warmupSetData = warmupSetData.copy(volume = warmupSetData.calculateVolume())
        } else if (warmupSetData is WeightSetData) {
            warmupSetData = warmupSetData.copy(volume = warmupSetData.calculateVolume())
        }
        val previousWarmupSetData = copySetData(warmupSetData)
        val warmupState = WorkoutState.Set(
            exercise.id,
            warmupSet,
            (warmupIndex * 2).toUInt(),
            previousWarmupSetData,
            currentSetDataState = mutableStateOf(warmupSetData),
            hasNoHistory = true,
            startTime = null,
            skipped = false,
            lowerBoundMaxHRPercent = exercise.lowerBoundMaxHRPercent,
            upperBoundMaxHRPercent = exercise.upperBoundMaxHRPercent,
            currentBodyWeight = bodyWeight.value,
            plateChangeResult = null,
            streak = exerciseInfo?.successfulSessionCounter?.toInt() ?: 0,
            progressionState = progressionState,
            isWarmupSet = true,
            equipment = equipment,
            isUnilateral = false,
            isCalibrationSet = false
        )
        warmupStates.add(warmupState)
        if (warmupIndex < warmups.size - 1) {
            val restSet = RestSet(UUID.randomUUID(), 60)
            val restState = WorkoutState.Rest(
                set = restSet,
                order = (warmupIndex * 2 + 1).toUInt(),
                currentSetDataState = mutableStateOf(initializeSetData(restSet)),
                exerciseId = exercise.id
            )
            warmupStates.add(restState)
        }
    }
    return warmupStates
}

private suspend fun WorkoutViewModel.createCalibrationSetExecutionState(
    exercise: Exercise,
    equipment: WeightLoadedEquipment?,
    currentState: WorkoutState.CalibrationLoadSelection,
    updatedSet: Set
): WorkoutState.Set {
    val exerciseInfo = withContext(dispatchers.io) { exerciseInfoDao.getExerciseInfoById(exercise.id) }
    val progressionData = exerciseProgressionByExerciseId[exercise.id]
    val progressionState = progressionData?.second
    var calibrationSetData = initializeSetData(updatedSet)
    calibrationSetData = when (calibrationSetData) {
        is BodyWeightSetData -> calibrationSetData.copy(
            relativeBodyWeightInKg = bodyWeight.value * (exercise.bodyWeightPercentage!! / 100),
            volume = calibrationSetData.calculateVolume()
        )
        is WeightSetData -> calibrationSetData.copy(volume = calibrationSetData.calculateVolume())
        else -> calibrationSetData
    }
    return WorkoutState.Set(
        exerciseId = exercise.id,
        set = updatedSet,
        setIndex = currentState.setIndex,
        previousSetData = copySetData(calibrationSetData),
        currentSetDataState = mutableStateOf(calibrationSetData),
        hasNoHistory = true,
        startTime = null,
        skipped = false,
        lowerBoundMaxHRPercent = exercise.lowerBoundMaxHRPercent,
        upperBoundMaxHRPercent = exercise.upperBoundMaxHRPercent,
        currentBodyWeight = bodyWeight.value,
        plateChangeResult = null,
        streak = exerciseInfo?.successfulSessionCounter?.toInt() ?: 0,
        progressionState = progressionState,
        isWarmupSet = false,
        equipment = equipment,
        isUnilateral = currentState.isUnilateral,
        intraSetTotal = null,
        intraSetCounter = 0u,
        isCalibrationSet = true
    )
}

// Removed: replaceCalibrationStateWithExecutionStates - now using insertStatesIntoExercise

private suspend fun WorkoutViewModel.calculateAndAssignPlateChanges(
    machine: WorkoutStateMachine,
    exerciseId: UUID,
    warmupStates: List<WorkoutState>,
    calibrationSetExecutionState: WorkoutState.Set,
    exercise: Exercise,
    equipment: Barbell
): WorkoutStateMachine {
    val setsForPlateCalculation = warmupStates.filterIsInstance<WorkoutState.Set>().toMutableList()
    setsForPlateCalculation.add(calibrationSetExecutionState)
    if (setsForPlateCalculation.isEmpty()) return machine
    
    val relativeBodyWeight = if (exercise.exerciseType == ExerciseType.BODY_WEIGHT) {
        bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
    } else {
        0.0
    }
    val weights = mutableListOf<Double>()
    for (setState in setsForPlateCalculation) {
        when (val set = setState.set) {
            is WeightSet -> weights.add(set.weight)
            is BodyWeightSet -> weights.add(relativeBodyWeight + set.additionalWeight)
            else -> { }
        }
    }
    if (weights.isEmpty()) return machine
    
    val plateChangeResults = withContext(dispatchers.default) {
        getPlateChangeResults(weights, equipment, emptyList())
    }
    if (plateChangeResults.size != setsForPlateCalculation.size) {
        Log.e("WorkoutViewModel", "Plate change results count (${plateChangeResults.size}) doesn't match sets count (${setsForPlateCalculation.size})")
        return machine
    }
    
    // Update plate changes in the sequence
    val updatedSequence = machine.stateSequence.map { item ->
        when (item) {
            is WorkoutStateSequenceItem.Container -> {
                when (val container = item.container) {
                    is WorkoutStateContainer.ExerciseState -> {
                        if (container.exerciseId == exerciseId) {
                            val updatedChildStates = container.childStates.mapIndexed { idx, state ->
                                if (state is WorkoutState.Set) {
                                    val setIndex = setsForPlateCalculation.indexOfFirst { calcState -> 
                                        calcState.set.id == state.set.id 
                                    }
                                    if (setIndex >= 0 && setIndex < plateChangeResults.size) {
                                        state.copy(plateChangeResult = plateChangeResults[setIndex])
                                    } else {
                                        state
                                    }
                                } else {
                                    state
                                }
                            }.toMutableList()
                            WorkoutStateSequenceItem.Container(container.copy(childStates = updatedChildStates))
                        } else {
                            item
                        }
                    }
                    is WorkoutStateContainer.SupersetState -> {
                        val updatedChildStates = container.childStates.mapIndexed { idx, state ->
                            if (state is WorkoutState.Set && state.exerciseId == exerciseId) {
                                val setIndex = setsForPlateCalculation.indexOfFirst { it.set.id == state.set.id }
                                if (setIndex >= 0 && idx < plateChangeResults.size) {
                                    state.copy(plateChangeResult = plateChangeResults[setIndex])
                                } else {
                                    state
                                }
                            } else {
                                state
                            }
                        }.toMutableList()
                        WorkoutStateSequenceItem.Container(container.copy(childStates = updatedChildStates))
                    }
                }
            }
            is WorkoutStateSequenceItem.RestBetweenExercises -> item
        }
    }
    
    return WorkoutStateMachine.fromSequence(updatedSequence, { LocalDateTime.now() }, machine.currentIndex)
}

private fun WorkoutViewModel.updateWorkSetsWithSelectedLoad(
    machine: WorkoutStateMachine,
    exercise: Exercise,
    selectedWeight: Double,
    afterInsertIndex: Int
): WorkoutStateMachine {
    val updatedSequence = machine.stateSequence.map { item ->
        when (item) {
            is WorkoutStateSequenceItem.Container -> {
                when (val container = item.container) {
                    is WorkoutStateContainer.ExerciseState -> {
                        if (container.exerciseId == exercise.id) {
                            val updatedChildStates = container.childStates.mapIndexed { idx, state ->
                                if (idx > afterInsertIndex && state is WorkoutState.Set &&
                                    !state.isWarmupSet && !state.isCalibrationSet) {
                                    val loadSelectionSetData = when (val existingSetData = state.currentSetData) {
                                        is WeightSetData -> {
                                            val newData = existingSetData.copy(actualWeight = selectedWeight)
                                            newData.copy(volume = newData.calculateVolume())
                                        }
                                        is BodyWeightSetData -> {
                                            val relativeBodyWeight = bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
                                            val newData = existingSetData.copy(
                                                additionalWeight = selectedWeight,
                                                relativeBodyWeightInKg = relativeBodyWeight
                                            )
                                            newData.copy(volume = newData.calculateVolume())
                                        }
                                        else -> existingSetData
                                    }
                                    state.currentSetData = loadSelectionSetData
                                    state.copy(previousSetData = loadSelectionSetData)
                                } else {
                                    state
                                }
                            }.toMutableList()
                            WorkoutStateSequenceItem.Container(container.copy(childStates = updatedChildStates))
                        } else {
                            item
                        }
                    }
                    is WorkoutStateContainer.SupersetState -> {
                        val updatedChildStates = container.childStates.mapIndexed { idx, state ->
                            if (state is WorkoutState.Set && state.exerciseId == exercise.id &&
                                idx > afterInsertIndex && !state.isWarmupSet && !state.isCalibrationSet) {
                                val loadSelectionSetData = when (val existingSetData = state.currentSetData) {
                                    is WeightSetData -> {
                                        val newData = existingSetData.copy(actualWeight = selectedWeight)
                                        newData.copy(volume = newData.calculateVolume())
                                    }
                                    is BodyWeightSetData -> {
                                        val relativeBodyWeight = bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
                                        val newData = existingSetData.copy(
                                            additionalWeight = selectedWeight,
                                            relativeBodyWeightInKg = relativeBodyWeight
                                        )
                                        newData.copy(volume = newData.calculateVolume())
                                    }
                                    else -> existingSetData
                                }
                                state.currentSetData = loadSelectionSetData
                                state.copy(previousSetData = loadSelectionSetData)
                            } else {
                                state
                            }
                        }.toMutableList()
                        WorkoutStateSequenceItem.Container(container.copy(childStates = updatedChildStates))
                    }
                }
            }
            is WorkoutStateSequenceItem.RestBetweenExercises -> item
        }
    }
    
    return WorkoutStateMachine.fromSequence(updatedSequence, { LocalDateTime.now() }, machine.currentIndex)
}

fun WorkoutViewModel.confirmCalibrationLoad() {
    viewModelScope.launch(dispatchers.io) {
        val machine = stateMachine ?: return@launch
        val currentState = machine.currentState as? WorkoutState.CalibrationLoadSelection ?: return@launch
        val selectedWeight = extractSelectedWeight(currentState) ?: return@launch
        val updatedSet = updateCalibrationSetWithWeight(currentState, selectedWeight) ?: return@launch
        val exercise = exercisesById[currentState.exerciseId] ?: return@launch
        val equipment = currentState.equipment

        val warmupStates = generateWarmupStates(exercise, equipment, currentState, selectedWeight)
        val calibrationSetExecutionState = createCalibrationSetExecutionState(
            exercise, equipment, currentState, updatedSet
        )
        
        val statesToInsert = mutableListOf<WorkoutState>()
        statesToInsert.addAll(warmupStates)
        statesToInsert.add(calibrationSetExecutionState)

        withContext(dispatchers.main) {
            // Find the container and child index for the current state (CalibrationLoadSelection)
            val currentFlatIndex = machine.currentIndex
            val position = machine.getContainerAndChildIndex(currentFlatIndex)
            if (position == null) return@withContext
            val (calibrationContainerIndex, calibrationChildIndex) = position

            // Replace CalibrationLoadSelection with inserted states
            val updatedSequence = machine.stateSequence.mapIndexed { seqIdx, item ->
                if (seqIdx == calibrationContainerIndex) {
                    when (item) {
                        is WorkoutStateSequenceItem.Container -> {
                            when (val container = item.container) {
                                is WorkoutStateContainer.ExerciseState -> {
                                    val updatedChildStates = container.childStates.toMutableList()
                                    updatedChildStates.removeAt(calibrationChildIndex)
                                    updatedChildStates.addAll(calibrationChildIndex, statesToInsert)
                                    WorkoutStateSequenceItem.Container(container.copy(childStates = updatedChildStates))
                                }
                                is WorkoutStateContainer.SupersetState -> {
                                    val updatedChildStates = container.childStates.toMutableList()
                                    updatedChildStates.removeAt(calibrationChildIndex)
                                    updatedChildStates.addAll(calibrationChildIndex, statesToInsert)
                                    WorkoutStateSequenceItem.Container(container.copy(childStates = updatedChildStates))
                                }
                            }
                        }
                        is WorkoutStateSequenceItem.RestBetweenExercises -> item
                    }
                } else {
                    item
                }
            }
            
            populateNextStateSetsForRest(updatedSequence)
            var updatedMachine = WorkoutStateMachine.fromSequence(updatedSequence, { LocalDateTime.now() }, currentFlatIndex)
            
            if (equipment is Barbell &&
                (exercise.exerciseType == ExerciseType.WEIGHT || exercise.exerciseType == ExerciseType.BODY_WEIGHT)
            ) {
                updatedMachine = calculateAndAssignPlateChanges(
                    updatedMachine, currentState.exerciseId, warmupStates, calibrationSetExecutionState, exercise, equipment
                )
            }
            
            updatedMachine = updateWorkSetsWithSelectedLoad(
                updatedMachine, exercise, selectedWeight, calibrationChildIndex + statesToInsert.size
            )
            
            // Repopulate nextStateSets so Rest states reference Set states that have plateChangeResult
            // (populateNextStateSetsForRest was called earlier with sequence before plate assignment)
            populateNextStateSetsForRest(updatedMachine.stateSequence)
            
            // Populate setStates and update state machine
            populateNextStateSets()
            stateMachine = updatedMachine
            updateStateFlowsFromMachine()
        }
    }
}
