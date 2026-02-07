package com.gabstra.myworkoutassistant.shared.workout.calibration

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
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import com.gabstra.myworkoutassistant.shared.workout.state.ContainerPosition
import com.gabstra.myworkoutassistant.shared.workout.state.ExerciseChildItem
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateEditor
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateMachine
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateContainer
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateSequenceItem
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateSequenceOps
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
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
            maxWarmups = 3
        )
    } else {
        WarmupPlanner.buildWarmupSets(
            availableTotals = availableTotals,
            workWeight = workWeightTotal,
            workReps = workReps,
            exercise = exercise,
            priorExercises = priorExercises,
            equipment = equipment,
            maxWarmups = 3
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

    val setReplacements = mutableMapOf<UUID, WorkoutState.Set>()
    setsForPlateCalculation.forEachIndexed { idx, setState ->
        if (idx < plateChangeResults.size) {
            setReplacements[setState.set.id] = setState.copy(plateChangeResult = plateChangeResults[idx])
        }
    }
    return machine.editSequence(transform = { sequence ->
        WorkoutStateSequenceOps.mapSequenceStates(sequence) { state ->
            if (state is WorkoutState.Set) {
                setReplacements[state.set.id] ?: state
            } else {
                state
            }
        }
    })
}

private fun WorkoutViewModel.updateWorkSetsWithSelectedLoad(
    machine: WorkoutStateMachine,
    exercise: Exercise,
    selectedWeight: Double,
    afterInsertIndex: Int
): WorkoutStateMachine {
    return WorkoutStateEditor.updateWorkSetsWithSelectedLoad(
        machine = machine,
        exercise = exercise,
        selectedWeight = selectedWeight,
        afterInsertIndex = afterInsertIndex,
        bodyWeightKg = bodyWeight.value
    )
}

fun WorkoutViewModel.confirmCalibrationLoad() {
    launchIO {
        val machine = stateMachine ?: return@launchIO
        val currentState = machine.currentState as? WorkoutState.CalibrationLoadSelection ?: return@launchIO
        val selectedWeight = extractSelectedWeight(currentState) ?: return@launchIO
        val updatedSet = updateCalibrationSetWithWeight(currentState, selectedWeight) ?: return@launchIO
        val exercise = exercisesById[currentState.exerciseId] ?: return@launchIO
        val equipment = currentState.equipment

        val warmupStates = generateWarmupStates(exercise, equipment, currentState, selectedWeight)
        val calibrationSetExecutionState = createCalibrationSetExecutionState(
            exercise, equipment, currentState, updatedSet
        )
        
        val warmupStatesToInsert = mutableListOf<WorkoutState>()
        warmupStatesToInsert.addAll(warmupStates)

        withContext(dispatchers.main) {
            val currentFlatIndex = machine.currentIndex
            val position = machine.getContainerAndChildIndex(currentFlatIndex)
            if (position == null) return@withContext

            // Keep CalibrationLoadSelection in place.
            // Insert warmups right after it, then insert calibration execution state
            // after warmups in CalibrationExecutionBlock (for Exercise container).
            var updatedMachine = when (position) {
                is ContainerPosition.Exercise -> machine.editSequence(transform = { sequence ->
                    sequence.mapIndexed { seqIdx, seqItem ->
                        if (seqIdx != position.containerSeqIndex || seqItem !is WorkoutStateSequenceItem.Container) {
                            seqItem
                        } else {
                            val container = seqItem.container as? WorkoutStateContainer.ExerciseState
                                ?: return@mapIndexed seqItem
                            val childItems = container.childItems.toMutableList()

                            val loadItem = childItems.getOrNull(position.childItemIndex)
                            if (loadItem is ExerciseChildItem.LoadSelectionBlock) {
                                val loadStates = loadItem.childStates.toMutableList()
                                val existingLoadSelection =
                                    loadStates.getOrNull(position.indexWithinChildItem) as? WorkoutState.CalibrationLoadSelection
                                if (existingLoadSelection != null) {
                                    loadStates[position.indexWithinChildItem] =
                                        existingLoadSelection.copy(isLoadConfirmed = true)
                                }
                                loadStates.addAll(position.indexWithinChildItem + 1, warmupStatesToInsert)
                                childItems[position.childItemIndex] = ExerciseChildItem.LoadSelectionBlock(loadStates)
                            }

                            val calibrationBlockIndex =
                                childItems.indexOfFirst { it is ExerciseChildItem.CalibrationExecutionBlock }
                            if (calibrationBlockIndex >= 0) {
                                val block = childItems[calibrationBlockIndex] as ExerciseChildItem.CalibrationExecutionBlock
                                val updatedCalibrationStates = block.childStates.toMutableList()
                                val existingCalibrationIndex = updatedCalibrationStates.indexOfFirst {
                                    it is WorkoutState.Set &&
                                        it.isCalibrationSet &&
                                        it.exerciseId == currentState.exerciseId &&
                                        it.set.id == calibrationSetExecutionState.set.id
                                }
                                if (existingCalibrationIndex >= 0) {
                                    updatedCalibrationStates[existingCalibrationIndex] = calibrationSetExecutionState
                                } else {
                                    updatedCalibrationStates.add(0, calibrationSetExecutionState)
                                }
                                childItems[calibrationBlockIndex] =
                                    ExerciseChildItem.CalibrationExecutionBlock(updatedCalibrationStates)
                            } else {
                                childItems.add(
                                    ExerciseChildItem.CalibrationExecutionBlock(
                                        mutableListOf(calibrationSetExecutionState)
                                    )
                                )
                            }

                            WorkoutStateSequenceItem.Container(container.copy(childItems = childItems))
                        }
                    }
                })
                is ContainerPosition.Superset -> machine.updateSupersetChildStates(position) { updatedChildStates ->
                    val existingLoadSelection =
                        updatedChildStates.getOrNull(position.childIndex) as? WorkoutState.CalibrationLoadSelection
                    if (existingLoadSelection != null) {
                        updatedChildStates[position.childIndex] = existingLoadSelection.copy(isLoadConfirmed = true)
                    }
                    val statesToInsert = warmupStatesToInsert + calibrationSetExecutionState
                    updatedChildStates.addAll(position.childIndex + 1, statesToInsert)
                    updatedChildStates
                }
            }

            populateNextStateForRest(updatedMachine)

            val afterInsertIndex = when (position) {
                is ContainerPosition.Exercise -> {
                    val flatInContainer = machine.getFlatIndexInContainer(position) ?: currentFlatIndex
                    flatInContainer + warmupStatesToInsert.size
                }
                is ContainerPosition.Superset -> position.childIndex + warmupStatesToInsert.size + 1
            }

            if (equipment is Barbell &&
                (exercise.exerciseType == ExerciseType.WEIGHT || exercise.exerciseType == ExerciseType.BODY_WEIGHT)
            ) {
                updatedMachine = calculateAndAssignPlateChanges(
                    updatedMachine, currentState.exerciseId, warmupStates, calibrationSetExecutionState, exercise, equipment
                )
            }

            updatedMachine = updateWorkSetsWithSelectedLoad(
                updatedMachine, exercise, selectedWeight, afterInsertIndex
            )
            
            // Repopulate nextState for Rest states so they reference states that have plateChangeResult
            // (populateNextStateForRest was called earlier before plate assignment)
            populateNextStateForRest(updatedMachine)
            
            // Populate setStates and update state machine. Move to the first inserted state.
            stateMachine = updatedMachine.withCurrentIndex(currentFlatIndex + 1)
            populateNextStateSets()
            updateStateFlowsFromMachine()
        }
    }
}

