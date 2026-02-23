package com.gabstra.myworkoutassistant.shared.workout.rir

import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateQueries
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.util.UUID

/**
 * Shared RIR application helpers used by both calibration and auto-regulation flows.
 */

internal fun WorkoutViewModel.extractWorkWeight(setData: SetData): Double = when (setData) {
    is WeightSetData -> setData.actualWeight
    is BodyWeightSetData -> setData.additionalWeight
    else -> 0.0
}

internal fun WorkoutViewModel.roundToNearestAvailableWeight(
    weight: Double,
    availableWeights: kotlin.collections.Set<Double>
): Double = if (availableWeights.isNotEmpty()) {
    availableWeights.minByOrNull { kotlin.math.abs(it - weight) } ?: weight
} else {
    weight
}

/**
 * @param indicesToUpdate when null, update all work sets; when non-null, update only sets at these indices in [exercise.sets]
 */
internal fun WorkoutViewModel.updateWorkSetsInExercise(
    exercise: Exercise,
    adjustedWeight: Double,
    availableWeights: kotlin.collections.Set<Double>,
    indicesToUpdate: kotlin.collections.Set<Int>? = null
): Pair<List<Set>, Map<UUID, Set>> {
    val updatedSets = exercise.sets.toMutableList()
    val setUpdates = mutableMapOf<UUID, Set>()
    for (i in exercise.sets.indices) {
        if (indicesToUpdate != null && i !in indicesToUpdate) continue
        val set = exercise.sets[i]
        when {
            set is com.gabstra.myworkoutassistant.shared.sets.RestSet -> continue
            set is WeightSet && (
                set.subCategory == com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory.CalibrationPendingSet ||
                    set.subCategory == com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory.WorkSet
                ) -> {
                val rounded = roundToNearestAvailableWeight(adjustedWeight, availableWeights)
                val updated = set.copy(weight = rounded, subCategory = com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory.WorkSet)
                updatedSets[i] = updated
                setUpdates[set.id] = updated
            }
            set is BodyWeightSet && (
                set.subCategory == com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory.CalibrationPendingSet ||
                    set.subCategory == com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory.WorkSet
                ) -> {
                val rounded = roundToNearestAvailableWeight(adjustedWeight, availableWeights)
                val updated = set.copy(additionalWeight = rounded, subCategory = com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory.WorkSet)
                updatedSets[i] = updated
                setUpdates[set.id] = updated
            }
            else -> { }
        }
    }
    return Pair(updatedSets, setUpdates)
}

internal fun WorkoutViewModel.updateWorkSetStateData(
    state: WorkoutState.Set,
    updatedSet: Set
): SetData = when (val setData = state.currentSetData) {
    is WeightSetData -> {
        val ws = updatedSet as? WeightSet
        if (ws != null) {
            val newData = setData.copy(actualWeight = ws.weight)
            newData.copy(volume = newData.calculateVolume())
        } else setData
    }
    is BodyWeightSetData -> {
        val bws = updatedSet as? BodyWeightSet
        if (bws != null) {
            val newData = setData.copy(additionalWeight = bws.additionalWeight)
            newData.copy(volume = newData.calculateVolume())
        } else setData
    }
    else -> setData
}

/**
 * Applies [setUpdates] to [state] when it is a work Set for [exerciseId]. Used by both calibration and auto-regulation.
 */
internal fun WorkoutViewModel.applyWorkSetUpdateToState(
    state: WorkoutState,
    exerciseId: UUID,
    setUpdates: Map<UUID, Set>
): WorkoutState {
    if (state !is WorkoutState.Set) return state
    if (WorkoutStateQueries.stateExerciseId(state) != exerciseId) return state
    val updatedSet = setUpdates[WorkoutStateQueries.stateSetId(state)] ?: return state
    if (state.isCalibrationSet) return state
    val newSetData = updateWorkSetStateData(state, updatedSet)
    state.set = updatedSet
    state.currentSetData = newSetData
    return state.copy(previousSetData = newSetData)
}
