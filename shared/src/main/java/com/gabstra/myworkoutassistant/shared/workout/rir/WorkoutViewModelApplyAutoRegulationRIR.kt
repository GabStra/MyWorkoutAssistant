package com.gabstra.myworkoutassistant.shared.workout.rir

import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.utils.CalibrationHelper
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateQueries
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateSequenceOps
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.UUID

/**
 * Applies auto-regulation RIR: stores RIR in [WorkoutState.AutoRegulationRIRSelection]'s set data,
 * adjusts weight for subsequent work sets only, removes the RIR selection state, and advances.
 */
fun WorkoutViewModel.applyAutoRegulationRIR(rir: Double, formBreaks: Boolean = false) {
    val machine = stateMachine ?: return
    val currentState = machine.currentState as? WorkoutState.AutoRegulationRIRSelection ?: return

    launchIO {
        currentState.currentSetData = currentState.currentSetData.withRIR(rir, forAutoRegulation = true)

        val workWeight = extractWorkWeight(currentState.currentSetData)
        val adjustedWeight = CalibrationHelper.applyCalibrationAdjustment(workWeight, rir, formBreaks)

        val exercise = exercisesById[currentState.exerciseId] ?: return@launchIO
        val equipment = currentState.equipmentId?.let { getEquipmentById(it) }
        val availableWeights = getWeightByEquipment(equipment)

        val sourceSetIndexInExerciseSets = exercise.sets.indexOfFirst { it.id == currentState.workSet.id }
        val subsequentIndices = if (sourceSetIndexInExerciseSets < 0) null else {
            exercise.sets.indices.filter { i ->
                i > sourceSetIndexInExerciseSets && exercise.sets[i] !is RestSet
            }.toSet()
        }

        val (updatedSets, setUpdates) = updateWorkSetsInExercise(
            exercise,
            adjustedWeight,
            availableWeights,
            indicesToUpdate = subsequentIndices
        )
        val updatedExercise = exercise.copy(sets = updatedSets)
        updateWorkout(exercise, updatedExercise)

        withContext(dispatchers.main) {
            initializeExercisesMaps(selectedWorkout.value)
            val m = stateMachine ?: return@withContext
            val currentIndex = m.currentIndex
            val sourceSetIndex = currentIndex - 1

            if (sourceSetIndex >= 0) {
                val tempMachine = m.withCurrentIndex(sourceSetIndex)
                stateMachine = tempMachine
                storeSetData()
            }

            val sequenceWithoutRIR = WorkoutStateSequenceOps.removeStateFromSequence(
                m.sequenceSnapshot(),
                currentState
            )
            val sourceSetId = currentState.workSet.id
            val rirAppliedSetData = currentState.currentSetData
            val fullyUpdatedSequence = WorkoutStateSequenceOps.mapSequenceStates(sequenceWithoutRIR) { state ->
                if (state is WorkoutState.Set &&
                    state.exerciseId == currentState.exerciseId &&
                    state.set.id == sourceSetId
                ) {
                    state.currentSetData = rirAppliedSetData
                }
                applyWorkSetUpdateToState(state, currentState.exerciseId, setUpdates)
            }

            stateMachine = m.withSequence(fullyUpdatedSequence, currentIndex)
            populateNextStateSets()
            updateStateFlowsFromMachine()

            if (equipment is Barbell &&
                (exercise.exerciseType == ExerciseType.WEIGHT || exercise.exerciseType == ExerciseType.BODY_WEIGHT) &&
                subsequentIndices != null && subsequentIndices.isNotEmpty()
            ) {
                val fromIndex = currentIndex
                val remainingStates = WorkoutStateQueries.remainingSetStatesForExercise(
                    machine = stateMachine!!,
                    fromIndexInclusive = fromIndex,
                    exerciseId = currentState.exerciseId
                )
                val weights = remainingStates.map { state ->
                    when (val set = state.set) {
                        is WeightSet -> set.weight
                        is BodyWeightSet ->
                            bodyWeight.value * (exercise.bodyWeightPercentage!! / 100) + set.additionalWeight
                        else -> 0.0
                    }
                }
                if (weights.size == remainingStates.size) {
                    recalculatePlatesForExerciseFromIndex(
                        currentState.exerciseId,
                        fromIndex,
                        weights,
                        equipment
                    )
                    stateMachine?.let { mp -> populateNextStateForRest(mp) }
                    updateStateFlowsFromMachine()
                }
            }
        }
    }
}
