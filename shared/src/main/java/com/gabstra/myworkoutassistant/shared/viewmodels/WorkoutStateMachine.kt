package com.gabstra.myworkoutassistant.shared.viewmodels

import java.time.LocalDateTime
import java.util.UUID

/**
 * Pure Kotlin state machine that encapsulates workout state queue/history logic.
 * Manages progression through workout states (Set, Rest, Completed) with support
 * for next, undo, and skip operations.
 */
data class WorkoutStateMachine(
    val allStates: List<WorkoutState>,
    internal val currentIndex: Int,
    private val timeProvider: () -> LocalDateTime = { LocalDateTime.now() }
) {
    init {
        require(currentIndex >= 0) { "currentIndex must be >= 0" }
        require(currentIndex < allStates.size) { "currentIndex must be < allStates.size" }
    }

    /**
     * Creates a new state machine starting at the first state.
     */
    companion object {
        fun fromStates(
            states: List<WorkoutState>,
            timeProvider: () -> LocalDateTime = { LocalDateTime.now() },
            startIndex: Int = 0
        ): WorkoutStateMachine {
            require(states.isNotEmpty()) { "States list cannot be empty" }
            require(startIndex >= 0) { "startIndex must be >= 0" }
            require(startIndex < states.size) { "startIndex must be < states.size" }
            return WorkoutStateMachine(states, currentIndex = startIndex, timeProvider)
        }
    }

    /**
     * Current workout state.
     */
    val currentState: WorkoutState
        get() = allStates[currentIndex]

    /**
     * History of completed states (all states before current index).
     */
    val history: List<WorkoutState>
        get() = allStates.subList(0, currentIndex)

    /**
     * Upcoming states (all states after current index, including Completed).
     */
    val nextStates: List<WorkoutState>
        get() = allStates.subList(currentIndex + 1, allStates.size)

    /**
     * The next state that will be reached by calling next(), or null if already at Completed.
     */
    val upcomingNext: WorkoutState?
        get() = if (currentIndex < allStates.size - 1) {
            allStates[currentIndex + 1]
        } else {
            null
        }

    /**
     * Whether we're at the start (no history).
     */
    val isAtStart: Boolean
        get() = currentIndex == 0

    /**
     * Whether we've reached the Completed state.
     */
    val isCompleted: Boolean
        get() = currentState is WorkoutState.Completed

    /**
     * Whether history is empty.
     */
    val isHistoryEmpty: Boolean
        get() = history.isEmpty()

    /**
     * Progress to the next state. Appends current state to history.
     * When progressing into Completed state, sets endWorkoutTime.
     */
    fun next(): WorkoutStateMachine {
        if (isCompleted) {
            return this
        }

        val nextIndex = currentIndex + 1
        require(nextIndex < allStates.size) { "Cannot advance beyond last state" }

        // If we're moving into Completed state, set endWorkoutTime
        val updatedStates = if (allStates[nextIndex] is WorkoutState.Completed) {
            val completedState = allStates[nextIndex] as WorkoutState.Completed
            val updatedCompleted = completedState.copy().apply {
                endWorkoutTime = timeProvider()
            }
            allStates.toMutableList().apply {
                this[nextIndex] = updatedCompleted
            }
        } else {
            allStates
        }

        return WorkoutStateMachine(updatedStates, nextIndex, timeProvider)
    }

    /**
     * Move back one step. Pops the last state from history and makes it current.
     * The previous current state becomes the first in nextStates.
     */
    fun undo(): WorkoutStateMachine {
        if (isAtStart) {
            return this
        }

        val previousIndex = currentIndex - 1
        return WorkoutStateMachine(allStates, previousIndex, timeProvider)
    }

    /**
     * Skip states until the predicate matches or we reach Completed.
     * Returns a new machine positioned at the matching state (or Completed if no match).
     */
    fun skipUntil(predicate: (WorkoutState) -> Boolean): WorkoutStateMachine {
        var targetIndex = currentIndex + 1

        while (targetIndex < allStates.size) {
            val state = allStates[targetIndex]
            if (predicate(state) || state is WorkoutState.Completed) {
                return WorkoutStateMachine(allStates, targetIndex, timeProvider)
            }
            targetIndex++
        }

        // If we reach here, we're at the last state (should be Completed)
        return WorkoutStateMachine(allStates, allStates.size - 1, timeProvider)
    }

    /**
     * Reposition the machine to a state matching the target setId.
     * Used during refresh operations to maintain position after regenerating states.
     */
    fun repositionToSetId(targetSetId: UUID): WorkoutStateMachine {
        // Find the first state with matching setId
        for (i in currentIndex until allStates.size) {
            val state = allStates[i]
            val setId = when (state) {
                is WorkoutState.Set -> state.set.id
                is WorkoutState.Rest -> state.set.id
                else -> null
            }
            if (setId == targetSetId) {
                return WorkoutStateMachine(allStates, i, timeProvider)
            }
        }
        // If not found, return current position
        return this
    }
}

