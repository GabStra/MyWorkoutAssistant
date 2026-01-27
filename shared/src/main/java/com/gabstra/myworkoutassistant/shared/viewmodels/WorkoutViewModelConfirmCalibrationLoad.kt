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
    val warmups: List<Pair<Double, Int>> = if (equipment is Barbell && exercise.exerciseType == ExerciseType.WEIGHT) {
        WarmupPlanner.buildWarmupSetsForBarbell(
            availableTotals = availableTotals,
            workWeight = workWeightTotal,
            workReps = workReps,
            barbell = equipment,
            initialSetup = emptyList(),
            maxWarmups = 4,
            context = null
        )
    } else {
        WarmupPlanner.buildWarmupSets(
            availableTotals = availableTotals,
            workWeight = workWeightTotal,
            workReps = workReps,
            maxWarmups = 4,
            context = null
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

private fun WorkoutViewModel.replaceCalibrationStateWithExecutionStates(
    machine: WorkoutStateMachine,
    warmupStates: List<WorkoutState>,
    calibrationSetExecutionState: WorkoutState.Set,
    statesToInsert: MutableList<WorkoutState>
): Pair<MutableList<WorkoutState>, Int> {
    val updatedStates = machine.allStates.toMutableList()
    val currentIndex = machine.currentIndex
    updatedStates.removeAt(currentIndex)
    statesToInsert.clear()
    statesToInsert.addAll(warmupStates)
    statesToInsert.add(calibrationSetExecutionState)
    updatedStates.addAll(currentIndex, statesToInsert)
    val warmupSetStates = warmupStates.filterIsInstance<WorkoutState.Set>()
    warmupSetStates.forEach { setStates.addLast(it) }
    setStates.addLast(calibrationSetExecutionState)
    return Pair(updatedStates, currentIndex)
}

private suspend fun WorkoutViewModel.calculateAndAssignPlateChanges(
    updatedStates: MutableList<WorkoutState>,
    warmupStates: List<WorkoutState>,
    calibrationSetExecutionState: WorkoutState.Set,
    exercise: Exercise,
    equipment: Barbell
) {
    val setsForPlateCalculation = warmupStates.filterIsInstance<WorkoutState.Set>().toMutableList()
    setsForPlateCalculation.add(calibrationSetExecutionState)
    if (setsForPlateCalculation.isEmpty()) return
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
    if (weights.isEmpty()) return
    val plateChangeResults = withContext(dispatchers.default) {
        getPlateChangeResults(weights, equipment, emptyList())
    }
    if (plateChangeResults.size != setsForPlateCalculation.size) {
        Log.e("WorkoutViewModel", "Plate change results count (${plateChangeResults.size}) doesn't match sets count (${setsForPlateCalculation.size})")
        return
    }
    for ((index, plateChangeResult) in plateChangeResults.withIndex()) {
        val setState = setsForPlateCalculation[index]
        val stateIndex = updatedStates.indexOf(setState)
        if (stateIndex < 0 || stateIndex >= updatedStates.size) continue
        val state = updatedStates[stateIndex] as? WorkoutState.Set ?: continue
        if (state.set.id != setState.set.id) continue
        updatedStates[stateIndex] = state.copy(plateChangeResult = plateChangeResult)
    }
}

private fun WorkoutViewModel.updateWorkSetsWithSelectedLoad(
    exercise: Exercise,
    selectedWeight: Double,
    updatedStates: MutableList<WorkoutState>,
    startIndex: Int
) {
    for (i in startIndex until updatedStates.size) {
        val state = updatedStates[i]
        if (state !is WorkoutState.Set ||
            state.exerciseId != exercise.id ||
            state.isWarmupSet ||
            state.isCalibrationSet
        ) continue
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
        val newState = state.copy(previousSetData = loadSelectionSetData)
        updatedStates[i] = newState
    }
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

        withContext(dispatchers.main) {
            val (updatedStates, newCurrentIndex) = replaceCalibrationStateWithExecutionStates(
                machine, warmupStates, calibrationSetExecutionState, statesToInsert
            )
            if (equipment is Barbell &&
                (exercise.exerciseType == ExerciseType.WEIGHT || exercise.exerciseType == ExerciseType.BODY_WEIGHT)
            ) {
                calculateAndAssignPlateChanges(
                    updatedStates, warmupStates, calibrationSetExecutionState, exercise, equipment
                )
            }
            updateWorkSetsWithSelectedLoad(
                exercise, selectedWeight, updatedStates,
                machine.currentIndex + statesToInsert.size
            )
            populateNextStateSets(updatedStates)
            stateMachine = WorkoutStateMachine(updatedStates, newCurrentIndex) { LocalDateTime.now() }
            updateStateFlowsFromMachine()
        }
    }
}
