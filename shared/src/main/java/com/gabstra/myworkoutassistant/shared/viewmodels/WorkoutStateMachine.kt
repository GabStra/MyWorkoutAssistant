package com.gabstra.myworkoutassistant.shared.viewmodels

import java.time.LocalDateTime
import java.util.UUID

/**
 * Position of a state in the sequence: which container and where inside it.
 * For [WorkoutStateContainer.ExerciseState] this includes which [ExerciseChildItem] and index within it (for block mutation).
 */
sealed class ContainerPosition {
    data class Exercise(
        val containerSeqIndex: Int,
        val childItemIndex: Int,
        val indexWithinChildItem: Int
    ) : ContainerPosition()

    data class Superset(
        val containerSeqIndex: Int,
        val childIndex: Int
    ) : ContainerPosition()
}

/**
 * Pure Kotlin state machine that encapsulates workout state queue/history logic.
 * Manages progression through workout states (Set, Rest, Completed) with support
 * for next, undo, and skip operations.
 * 
 * Internally uses a hierarchical structure with containers (ExerciseState/SupersetState)
 * but exposes a flattened list of states for navigation.
 */
data class WorkoutStateMachine(
    internal val stateSequence: List<WorkoutStateSequenceItem>,
    internal val currentIndex: Int,
    private val timeProvider: () -> LocalDateTime = { LocalDateTime.now() }
) {
    init {
        require(currentIndex >= 0) { "currentIndex must be >= 0" }
        require(currentIndex < allStates.size) { "currentIndex must be < allStates.size" }
    }

    /**
     * Flattened list of all workout states computed from stateSequence.
     * This is what pagination and navigation work with.
     */
    val allStates: List<WorkoutState>
        get() = buildList {
            stateSequence.forEach { item ->
                when (item) {
                    is WorkoutStateSequenceItem.Container -> {
                        when (val container = item.container) {
                            is WorkoutStateContainer.ExerciseState -> addAll(container.flattenChildItems())
                            is WorkoutStateContainer.SupersetState -> addAll(container.childStates)
                        }
                    }
                    is WorkoutStateSequenceItem.RestBetweenExercises -> {
                        add(item.rest)
                    }
                }
            }
        }

    /**
     * Creates a new state machine from a sequence of containers and Rest states.
     */
    companion object {
        fun fromSequence(
            sequence: List<WorkoutStateSequenceItem>,
            timeProvider: () -> LocalDateTime = { LocalDateTime.now() },
            startIndex: Int = 0
        ): WorkoutStateMachine {
            val machine = WorkoutStateMachine(sequence, currentIndex = startIndex, timeProvider)
            require(machine.allStates.isNotEmpty()) { "State sequence cannot be empty" }
            require(startIndex >= 0) { "startIndex must be >= 0" }
            require(startIndex < machine.allStates.size) { "startIndex must be < allStates.size" }
            return machine
        }

        /**
         * Creates a new state machine from a flat list of states (backward compatibility).
         * Wraps all states in a single ExerciseState container.
         */
        @Deprecated("Use fromSequence instead", ReplaceWith("fromSequence"))
        fun fromStates(
            states: List<WorkoutState>,
            timeProvider: () -> LocalDateTime = { LocalDateTime.now() },
            startIndex: Int = 0
        ): WorkoutStateMachine {
            require(states.isNotEmpty()) { "States list cannot be empty" }
            require(startIndex >= 0) { "startIndex must be >= 0" }
            require(startIndex < states.size) { "startIndex must be < states.size" }
            // Create a dummy exercise container for backward compatibility (each state as Normal)
            val dummyExerciseId = UUID.randomUUID()
            val container = WorkoutStateContainer.ExerciseState(
                exerciseId = dummyExerciseId,
                childItems = states.map { ExerciseChildItem.Normal(it) }.toMutableList()
            )
            val sequence = listOf(WorkoutStateSequenceItem.Container(container))
            return WorkoutStateMachine(sequence, currentIndex = startIndex, timeProvider)
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

        // Rebuild stateSequence with updated states
        val updatedSequence = rebuildSequenceWithUpdatedStates(updatedStates)
        return WorkoutStateMachine(updatedSequence, nextIndex, timeProvider)
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
        return WorkoutStateMachine(stateSequence, previousIndex, timeProvider)
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
                return WorkoutStateMachine(stateSequence, targetIndex, timeProvider)
            }
            targetIndex++
        }

        // If we reach here, we're at the last state (should be Completed)
        return WorkoutStateMachine(stateSequence, allStates.size - 1, timeProvider)
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
                return WorkoutStateMachine(stateSequence, i, timeProvider)
            }
        }
        // If not found, return current position
        return this
    }

    /**
     * Insert states into an ExerciseState container (into the flattened position).
     * Returns a new WorkoutStateMachine with the inserted states.
     */
    fun insertStatesIntoExercise(
        exerciseId: UUID,
        states: List<WorkoutState>,
        afterFlatIndexInContainer: Int?
    ): WorkoutStateMachine {
        val updatedSequence = stateSequence.map { item ->
            when (item) {
                is WorkoutStateSequenceItem.Container -> {
                    when (val container = item.container) {
                        is WorkoutStateContainer.ExerciseState -> {
                            if (container.exerciseId == exerciseId) {
                                val flatSize = container.flattenChildItems().size
                                val insertAt = if (afterFlatIndexInContainer != null) {
                                    (afterFlatIndexInContainer + 1).coerceIn(0, flatSize)
                                } else {
                                    flatSize
                                }
                                val updatedChildItems = insertIntoExerciseChildItems(
                                    container.childItems,
                                    insertAt,
                                    states
                                )
                                WorkoutStateSequenceItem.Container(
                                    container.copy(childItems = updatedChildItems)
                                )
                            } else {
                                item
                            }
                        }
                        is WorkoutStateContainer.SupersetState -> {
                            val updatedChildStates = container.childStates.toMutableList()
                            var found = false
                            for (i in updatedChildStates.indices.reversed()) {
                                val state = updatedChildStates[i]
                                if (state is WorkoutState.Set && state.exerciseId == exerciseId) {
                                    val insertIndex = if (afterFlatIndexInContainer != null) {
                                        (i + afterFlatIndexInContainer + 1).coerceIn(0, updatedChildStates.size)
                                    } else {
                                        i + 1
                                    }
                                    updatedChildStates.addAll(insertIndex, states)
                                    found = true
                                    break
                                }
                            }
                            if (found) {
                                WorkoutStateSequenceItem.Container(
                                    container.copy(childStates = updatedChildStates)
                                )
                            } else {
                                item
                            }
                        }
                    }
                }
                is WorkoutStateSequenceItem.RestBetweenExercises -> item
            }
        }
        return WorkoutStateMachine(updatedSequence, currentIndex, timeProvider)
    }

    private fun insertIntoExerciseChildItems(
        childItems: MutableList<ExerciseChildItem>,
        insertAtFlatIndex: Int,
        states: List<WorkoutState>
    ): MutableList<ExerciseChildItem> {
        var flatPos = 0
        val result = childItems.toMutableList()
        // insertAtFlatIndex is where the first new state should go; find the segment containing (insertAtFlatIndex - 1) so we insert after it
        val afterIndex = (insertAtFlatIndex - 1).coerceAtLeast(0)
        for (i in result.indices) {
            val elem = result[i]
            val size = when (elem) {
                is ExerciseChildItem.Normal -> 1
                is ExerciseChildItem.CalibrationExecutionBlock -> elem.childStates.size
                is ExerciseChildItem.LoadSelectionBlock -> elem.childStates.size
                is ExerciseChildItem.UnilateralSetBlock -> elem.childStates.size
            }
            if (flatPos + size > afterIndex) {
                val localIndex = insertAtFlatIndex - flatPos
                when (elem) {
                    is ExerciseChildItem.Normal -> {
                        val newNormals = states.map { ExerciseChildItem.Normal(it) }
                        result.addAll(i + 1, newNormals)
                    }
                    is ExerciseChildItem.CalibrationExecutionBlock -> {
                        result[i] = ExerciseChildItem.CalibrationExecutionBlock(
                            (elem.childStates.toMutableList().apply { addAll(localIndex, states) })
                        )
                    }
                    is ExerciseChildItem.LoadSelectionBlock -> {
                        result[i] = ExerciseChildItem.LoadSelectionBlock(
                            (elem.childStates.toMutableList().apply { addAll(localIndex, states) })
                        )
                    }
                    is ExerciseChildItem.UnilateralSetBlock -> {
                        result[i] = ExerciseChildItem.UnilateralSetBlock(
                            (elem.childStates.toMutableList().apply { addAll(localIndex, states) })
                        )
                    }
                }
                return result
            }
            flatPos += size
        }
        result.addAll(states.map { ExerciseChildItem.Normal(it) })
        return result
    }

    /**
     * Returns the container position for the state at the given flat index in allStates.
     * For ExerciseState returns [ContainerPosition.Exercise] with childItemIndex and indexWithinChildItem for block mutation.
     * Returns null if flatIndex is out of range or points to a RestBetweenExercises.
     */
    fun getContainerAndChildIndex(flatIndex: Int): ContainerPosition? {
        if (flatIndex < 0 || flatIndex >= allStates.size) return null
        var currentFlatPos = 0
        for ((seqIdx, item) in stateSequence.withIndex()) {
            when (item) {
                is WorkoutStateSequenceItem.Container -> {
                    when (val container = item.container) {
                        is WorkoutStateContainer.ExerciseState -> {
                            val flatSize = container.flattenChildItems().size
                            if (currentFlatPos <= flatIndex && flatIndex < currentFlatPos + flatSize) {
                                val flatIndexInContainer = flatIndex - currentFlatPos
                                val (childItemIndex, indexWithinChildItem) =
                                    getExerciseChildItemAndIndex(container, flatIndexInContainer)
                                    ?: return null
                                return ContainerPosition.Exercise(seqIdx, childItemIndex, indexWithinChildItem)
                            }
                            currentFlatPos += flatSize
                        }
                        is WorkoutStateContainer.SupersetState -> {
                            val size = container.childStates.size
                            if (currentFlatPos <= flatIndex && flatIndex < currentFlatPos + size) {
                                return ContainerPosition.Superset(seqIdx, flatIndex - currentFlatPos)
                            }
                            currentFlatPos += size
                        }
                    }
                }
                is WorkoutStateSequenceItem.RestBetweenExercises -> {
                    if (currentFlatPos == flatIndex) return null
                    currentFlatPos++
                }
            }
        }
        return null
    }

    /**
     * For an ExerciseState and a flat index within it, returns (childItemIndex, indexWithinChildItem).
     */
    private fun getExerciseChildItemAndIndex(
        container: WorkoutStateContainer.ExerciseState,
        flatIndexInContainer: Int
    ): Pair<Int, Int>? {
        var flatPos = 0
        for (i in container.childItems.indices) {
            val elem = container.childItems[i]
            val size = when (elem) {
                is ExerciseChildItem.Normal -> 1
                is ExerciseChildItem.CalibrationExecutionBlock -> elem.childStates.size
                is ExerciseChildItem.LoadSelectionBlock -> elem.childStates.size
                is ExerciseChildItem.UnilateralSetBlock -> elem.childStates.size
            }
            if (flatIndexInContainer < flatPos + size) {
                return Pair(i, flatIndexInContainer - flatPos)
            }
            flatPos += size
        }
        return null
    }

    /**
     * Get the ExerciseState container containing the current state.
     */
    fun getCurrentExerciseContainer(): WorkoutStateContainer.ExerciseState? {
        val currentState = allStates[currentIndex]
        return findContainerForState(currentState) as? WorkoutStateContainer.ExerciseState
    }

    /**
     * Get the SupersetState container containing the current state.
     */
    fun getCurrentSupersetContainer(): WorkoutStateContainer.SupersetState? {
        val currentState = allStates[currentIndex]
        return findContainerForState(currentState) as? WorkoutStateContainer.SupersetState
    }

    /**
     * Get all states for a specific exercise from its container (flattened order).
     */
    fun getStatesForExercise(exerciseId: UUID): List<WorkoutState> {
        return stateSequence.flatMap { item ->
            when (item) {
                is WorkoutStateSequenceItem.Container -> {
                    when (val container = item.container) {
                        is WorkoutStateContainer.ExerciseState -> {
                            if (container.exerciseId == exerciseId) {
                                container.flattenChildItems()
                            } else {
                                emptyList()
                            }
                        }
                        is WorkoutStateContainer.SupersetState -> {
                            container.childStates.filter { state ->
                                when (state) {
                                    is WorkoutState.Set -> state.exerciseId == exerciseId
                                    is WorkoutState.CalibrationLoadSelection -> state.exerciseId == exerciseId
                                    is WorkoutState.CalibrationRIRSelection -> state.exerciseId == exerciseId
                                    else -> false
                                }
                            }
                        }
                    }
                }
                is WorkoutStateSequenceItem.RestBetweenExercises -> emptyList()
            }
        }
    }

    /**
     * Helper to find the container containing a specific state.
     */
    private fun findContainerForState(targetState: WorkoutState): WorkoutStateContainer? {
        val targetIndex = allStates.indexOf(targetState)
        if (targetIndex < 0) return null
        var currentFlatIndex = 0
        for (item in stateSequence) {
            when (item) {
                is WorkoutStateSequenceItem.Container -> {
                    val container = item.container
                    val size = when (container) {
                        is WorkoutStateContainer.ExerciseState -> container.flattenChildItems().size
                        is WorkoutStateContainer.SupersetState -> container.childStates.size
                    }
                    val endIndex = currentFlatIndex + size
                    if (targetIndex < endIndex) {
                        return container
                    }
                    currentFlatIndex = endIndex
                }
                is WorkoutStateSequenceItem.RestBetweenExercises -> {
                    if (targetState == item.rest) {
                        return null
                    }
                    currentFlatIndex++
                }
            }
        }
        return null
    }

    /**
     * Rebuild stateSequence with updated states (for next() when Completed state is updated).
     */
    private fun rebuildSequenceWithUpdatedStates(updatedStates: List<WorkoutState>): List<WorkoutStateSequenceItem> {
        val result = mutableListOf<WorkoutStateSequenceItem>()
        var stateIndex = 0

        for (item in stateSequence) {
            when (item) {
                is WorkoutStateSequenceItem.Container -> {
                    when (val container = item.container) {
                        is WorkoutStateContainer.ExerciseState -> {
                            val updatedChildItems = mutableListOf<ExerciseChildItem>()
                            for (childItem in container.childItems) {
                                when (childItem) {
                                    is ExerciseChildItem.Normal -> {
                                        updatedChildItems.add(
                                            ExerciseChildItem.Normal(updatedStates[stateIndex++])
                                        )
                                    }
                                    is ExerciseChildItem.CalibrationExecutionBlock -> {
                                        val n = childItem.childStates.size
                                        updatedChildItems.add(
                                            ExerciseChildItem.CalibrationExecutionBlock(
                                                updatedStates.subList(stateIndex, stateIndex + n).toMutableList()
                                            )
                                        )
                                        stateIndex += n
                                    }
                                    is ExerciseChildItem.LoadSelectionBlock -> {
                                        val n = childItem.childStates.size
                                        updatedChildItems.add(
                                            ExerciseChildItem.LoadSelectionBlock(
                                                updatedStates.subList(stateIndex, stateIndex + n).toMutableList()
                                            )
                                        )
                                        stateIndex += n
                                    }
                                    is ExerciseChildItem.UnilateralSetBlock -> {
                                        val n = childItem.childStates.size
                                        updatedChildItems.add(
                                            ExerciseChildItem.UnilateralSetBlock(
                                                updatedStates.subList(stateIndex, stateIndex + n).toMutableList()
                                            )
                                        )
                                        stateIndex += n
                                    }
                                }
                            }
                            result.add(WorkoutStateSequenceItem.Container(
                                container.copy(childItems = updatedChildItems)
                            ))
                        }
                        is WorkoutStateContainer.SupersetState -> {
                            val childCount = container.childStates.size
                            val updatedChildStates = updatedStates.subList(stateIndex, stateIndex + childCount).toMutableList()
                            result.add(WorkoutStateSequenceItem.Container(
                                container.copy(childStates = updatedChildStates)
                            ))
                            stateIndex += childCount
                        }
                    }
                }
                is WorkoutStateSequenceItem.RestBetweenExercises -> {
                    if (stateIndex < updatedStates.size && updatedStates[stateIndex] == item.rest) {
                        result.add(item)
                        stateIndex++
                    } else {
                        result.add(item)
                    }
                }
            }
        }
        return result
    }
}

