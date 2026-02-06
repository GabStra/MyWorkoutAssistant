package com.gabstra.myworkoutassistant.shared.workout.state

import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.util.UUID

internal object WorkoutStateEditor {
    fun applyExecutedSetDataToSequence(
        sequence: List<WorkoutStateSequenceItem>,
        executedSetsHistorySnapshot: List<SetHistory>
    ): List<WorkoutStateSequenceItem> {
        return WorkoutStateSequenceOps.mapSequenceStates(sequence) { state ->
            when (state) {
                is WorkoutState.Set -> {
                    val setHistory = executedSetsHistorySnapshot.firstOrNull { setHistory ->
                        WorkoutStateQueries.matchesSetHistory(
                            setHistory,
                            state.set.id,
                            state.setIndex,
                            state.exerciseId
                        )
                    }
                    if (setHistory != null) {
                        state.currentSetData = setHistory.setData
                    }
                    state
                }
                is WorkoutState.Rest -> {
                    val setHistory = executedSetsHistorySnapshot.firstOrNull { setHistory ->
                        WorkoutStateQueries.matchesSetHistory(
                            setHistory,
                            state.set.id,
                            state.order,
                            state.exerciseId
                        )
                    }
                    if (setHistory != null) {
                        state.currentSetData = setHistory.setData
                    }
                    state
                }
                else -> state
            }
        }
    }

    fun populateRestNextState(machine: WorkoutStateMachine) {
        val allStates = machine.allStates
        for (i in allStates.indices) {
            val currentState = allStates[i]
            if (currentState is WorkoutState.Rest) {
                currentState.nextState = allStates.getOrNull(i + 1)
            }
        }
    }

    fun updateCurrentState(machine: WorkoutStateMachine, updatedState: WorkoutState): WorkoutStateMachine =
        machine.updateStateAtFlatIndex(machine.currentIndex, updatedState)

    fun replaceBySetId(
        machine: WorkoutStateMachine,
        replacements: Map<UUID, WorkoutState>
    ): WorkoutStateMachine = machine.replaceStatesById({ it.setIdOrNull() }, replacements)

    fun updateWorkSetsWithSelectedLoad(
        machine: WorkoutStateMachine,
        exercise: Exercise,
        selectedWeight: Double,
        afterInsertIndex: Int,
        bodyWeightKg: Double
    ): WorkoutStateMachine {
        return machine.editSequence(transform = { sequence ->
            sequence.map { item ->
                when (item) {
                    is WorkoutStateSequenceItem.Container -> {
                        when (val container = item.container) {
                            is WorkoutStateContainer.ExerciseState -> {
                                if (container.exerciseId == exercise.id) {
                                    val flatStates = WorkoutStateSequenceOps.flattenExerciseContainer(container)
                                    val updatedFlat = flatStates.mapIndexed { idx, state ->
                                        updateStateForSelectedLoad(
                                            state = state,
                                            selectedWeight = selectedWeight,
                                            exercise = exercise,
                                            bodyWeightKg = bodyWeightKg,
                                            shouldUpdate = idx > afterInsertIndex
                                        )
                                    }
                                    val updatedChildItems = WorkoutStateSequenceOps.rebuildExerciseChildItemsFromFlat(
                                        container.childItems,
                                        updatedFlat
                                    )
                                    WorkoutStateSequenceItem.Container(container.copy(childItems = updatedChildItems))
                                } else {
                                    item
                                }
                            }
                            is WorkoutStateContainer.SupersetState -> {
                                val updatedChildStates = container.childStates.mapIndexed { idx, state ->
                                    updateStateForSelectedLoad(
                                        state = state,
                                        selectedWeight = selectedWeight,
                                        exercise = exercise,
                                        bodyWeightKg = bodyWeightKg,
                                        shouldUpdate = idx > afterInsertIndex
                                    )
                                }.toMutableList()
                                WorkoutStateSequenceItem.Container(container.copy(childStates = updatedChildStates))
                            }
                        }
                    }
                    is WorkoutStateSequenceItem.RestBetweenExercises -> item
                }
            }
        })
    }

    private fun updateStateForSelectedLoad(
        state: WorkoutState,
        selectedWeight: Double,
        exercise: Exercise,
        bodyWeightKg: Double,
        shouldUpdate: Boolean
    ): WorkoutState {
        if (!shouldUpdate || state !is WorkoutState.Set || state.isWarmupSet || state.isCalibrationSet) {
            return state
        }

        val loadSelectionSetData = when (val existingSetData = state.currentSetData) {
            is WeightSetData -> {
                val newData = existingSetData.copy(actualWeight = selectedWeight)
                newData.copy(volume = newData.calculateVolume())
            }
            is BodyWeightSetData -> {
                val relativeBodyWeight = bodyWeightKg * (exercise.bodyWeightPercentage!! / 100)
                val newData = existingSetData.copy(
                    additionalWeight = selectedWeight,
                    relativeBodyWeightInKg = relativeBodyWeight
                )
                newData.copy(volume = newData.calculateVolume())
            }
            else -> existingSetData
        }
        state.currentSetData = loadSelectionSetData
        return state.copy(previousSetData = loadSelectionSetData)
    }
}

