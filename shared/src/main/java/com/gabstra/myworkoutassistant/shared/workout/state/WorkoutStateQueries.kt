package com.gabstra.myworkoutassistant.shared.workout.state

import com.gabstra.myworkoutassistant.shared.SetHistory
import java.util.UUID

internal object WorkoutStateQueries {
    data class StateHistoryIdentity(
        val setId: UUID,
        val order: UInt,
        val exerciseId: UUID?
    )

    fun stateSetId(state: WorkoutState): UUID? = state.setIdOrNull()

    fun stateExerciseId(state: WorkoutState): UUID? = state.exerciseIdOrNull()

    fun isCalibrationRelated(state: WorkoutState): Boolean = state.isCalibrationState()

    fun isNavigableSet(state: WorkoutState, excludedSetId: UUID? = null): Boolean {
        val setState = state as? WorkoutState.Set ?: return false
        if (setState.isCalibrationSet) return false
        return excludedSetId == null || setState.set.id != excludedSetId
    }

    fun stateMatchesSetAndExercise(
        state: WorkoutState,
        targetSetId: UUID?,
        targetExerciseId: UUID?
    ): Boolean = stateSetId(state) == targetSetId && stateExerciseId(state) == targetExerciseId

    fun stateHistoryIdentity(state: WorkoutState): StateHistoryIdentity? = when (state) {
        is WorkoutState.Set -> StateHistoryIdentity(
            setId = state.set.id,
            order = state.setIndex,
            exerciseId = state.exerciseId
        )
        is WorkoutState.Rest -> StateHistoryIdentity(
            setId = state.set.id,
            order = state.order,
            exerciseId = state.exerciseId
        )
        else -> null
    }

    fun matchesExerciseAndOrder(
        state: WorkoutState,
        exerciseId: UUID?,
        order: UInt
    ): Boolean {
        val identity = stateHistoryIdentity(state) ?: return false
        return identity.exerciseId == exerciseId && identity.order == order
    }

    fun stateSetObjectOrNull(state: WorkoutState): com.gabstra.myworkoutassistant.shared.sets.Set? = when (state) {
        is WorkoutState.Set -> state.set
        is WorkoutState.Rest -> state.set
        else -> null
    }

    fun matchesSetHistory(
        setHistory: SetHistory,
        setId: UUID,
        order: UInt,
        exerciseId: UUID?
    ): Boolean {
        if (setHistory.setId != setId || setHistory.order != order) {
            return false
        }
        return setHistory.exerciseId == null ||
            exerciseId == null ||
            setHistory.exerciseId == exerciseId
    }

    fun orderedUniqueSetIds(states: List<WorkoutState>): List<UUID> {
        val orderedSetIds = mutableListOf<UUID>()
        for (state in states) {
            val setId = stateSetId(state) ?: continue
            if (setId !in orderedSetIds) {
                orderedSetIds.add(setId)
            }
        }
        return orderedSetIds
    }

    /**
     * Logical workout sets for counters: includes all Set states (including calibration execution sets),
     * excludes Rest and calibration selection states.
     */
    fun orderedUniqueLogicalSetIds(states: List<WorkoutState>): List<UUID> {
        val orderedSetIds = mutableListOf<UUID>()
        for (state in states) {
            val setId = when (state) {
                is WorkoutState.Set -> state.set.id
                else -> null
            } ?: continue
            if (setId !in orderedSetIds) {
                orderedSetIds.add(setId)
            }
        }
        return orderedSetIds
    }

    fun findPreviousIndex(
        machine: WorkoutStateMachine,
        fromIndexExclusive: Int = machine.currentIndex,
        predicate: (WorkoutState) -> Boolean
    ): Int? {
        for (i in fromIndexExclusive - 1 downTo 0) {
            if (predicate(machine.allStates[i])) {
                return i
            }
        }
        return null
    }

    fun findNextIndex(
        machine: WorkoutStateMachine,
        fromIndexExclusive: Int = machine.currentIndex,
        predicate: (WorkoutState) -> Boolean
    ): Int? {
        for (i in fromIndexExclusive + 1 until machine.allStates.size) {
            if (predicate(machine.allStates[i])) {
                return i
            }
        }
        return null
    }

    fun statesForExercise(machine: WorkoutStateMachine, exerciseId: UUID): List<WorkoutState> =
        machine.getStatesForExercise(exerciseId)

    fun remainingSetStatesForExercise(
        machine: WorkoutStateMachine,
        fromIndexInclusive: Int,
        exerciseId: UUID
    ): List<WorkoutState.Set> {
        if (fromIndexInclusive < 0 || fromIndexInclusive >= machine.allStates.size) {
            return emptyList()
        }
        return machine.allStates
            .subList(fromIndexInclusive, machine.allStates.size)
            .filterIsInstance<WorkoutState.Set>()
            .filter { it.exerciseId == exerciseId }
    }

    fun previousSetStateForExercise(
        machine: WorkoutStateMachine,
        beforeIndexExclusive: Int,
        exerciseId: UUID
    ): WorkoutState.Set? {
        if (beforeIndexExclusive <= 0) return null
        return machine.allStates
            .subList(0, beforeIndexExclusive.coerceAtMost(machine.allStates.size))
            .filterIsInstance<WorkoutState.Set>()
            .lastOrNull { it.exerciseId == exerciseId }
    }

    fun collectSetIdsAfterIndex(machine: WorkoutStateMachine, index: Int): Set<UUID> {
        if (index + 1 >= machine.allStates.size) return emptySet()
        val ids = mutableSetOf<UUID>()
        for (i in index + 1 until machine.allStates.size) {
            val setId = stateSetId(machine.allStates[i])
            if (setId != null) ids.add(setId)
        }
        return ids
    }
}

