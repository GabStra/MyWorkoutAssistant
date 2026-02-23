package com.gabstra.myworkoutassistant.shared.workout.state

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
 * Manages progression through workout states (Set, Rest, calibration states) with support
 * for next, undo, and skip operations.
 * 
 * Internally uses a hierarchical structure with containers (ExerciseState/SupersetState)
 * but exposes a flattened list of states for navigation.
 */
data class WorkoutStateMachine(
    private val stateSequence: List<WorkoutStateSequenceItem>,
    internal val currentIndex: Int,
    private val timeProvider: () -> LocalDateTime = { LocalDateTime.now() }
) {
    fun sequenceSnapshot(): List<WorkoutStateSequenceItem> = stateSequence

    init {
        val disallowedBoundaryState = allStates.firstOrNull { state ->
            state is WorkoutState.Preparing || state is WorkoutState.Completed
        }
        require(disallowedBoundaryState == null) {
            "WorkoutStateMachine sequence cannot contain Preparing or Completed states"
        }
        require(currentIndex >= 0) { "currentIndex must be >= 0" }
        require(currentIndex < allStates.size) { "currentIndex must be < allStates.size" }
    }

    /**
     * Flattened list of all workout states computed from stateSequence.
     * This is what pagination and navigation work with.
     */
    val allStates: List<WorkoutState>
        get() = WorkoutStateSequenceOps.flattenSequence(stateSequence)

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
     * Upcoming states (all states after current index).
     */
    val nextStates: List<WorkoutState>
        get() = allStates.subList(currentIndex + 1, allStates.size)

    /**
     * The next state that will be reached by calling next(), or null if already at the last state.
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
     * Whether we've reached the last state in the flattened sequence.
     */
    val isCompleted: Boolean
        get() = currentIndex >= allStates.lastIndex

    /**
     * Whether history is empty.
     */
    val isHistoryEmpty: Boolean
        get() = history.isEmpty()

    internal fun withSequence(
        updatedSequence: List<WorkoutStateSequenceItem>,
        newIndex: Int = currentIndex
    ): WorkoutStateMachine = WorkoutStateMachine(updatedSequence, newIndex, timeProvider)

    internal fun withCurrentIndex(newIndex: Int): WorkoutStateMachine =
        WorkoutStateMachine(stateSequence, newIndex, timeProvider)

    internal fun editSequence(
        transform: (List<WorkoutStateSequenceItem>) -> List<WorkoutStateSequenceItem>,
        newIndex: Int = currentIndex
    ): WorkoutStateMachine = withSequence(transform(stateSequence), newIndex)

    internal fun mapStates(mapper: (WorkoutState) -> WorkoutState): WorkoutStateMachine =
        withSequence(WorkoutStateSequenceOps.mapSequenceStates(stateSequence, mapper), currentIndex)

    internal fun mapStatesIndexed(mapper: (Int, WorkoutState) -> WorkoutState): WorkoutStateMachine =
        withSequence(WorkoutStateSequenceOps.mapSequenceStatesIndexed(stateSequence, mapper), currentIndex)

    internal fun mapStatesForExercise(
        exerciseId: UUID,
        mapper: (WorkoutState) -> WorkoutState
    ): WorkoutStateMachine = withSequence(
        WorkoutStateSequenceOps.mapStatesForExercise(stateSequence, exerciseId, mapper),
        currentIndex
    )

    internal fun replaceStatesById(
        idSelector: (WorkoutState) -> UUID?,
        replacements: Map<UUID, WorkoutState>
    ): WorkoutStateMachine = withSequence(
        WorkoutStateSequenceOps.replaceStatesById(stateSequence, idSelector, replacements),
        currentIndex
    )

    internal fun updateStateAtFlatIndex(flatIndex: Int, updatedState: WorkoutState): WorkoutStateMachine =
        withSequence(
            WorkoutStateSequenceOps.updateStateAtFlatIndex(stateSequence, flatIndex, updatedState),
            currentIndex
        )

    internal fun updateCurrentState(updatedState: WorkoutState): WorkoutStateMachine =
        updateStateAtFlatIndex(currentIndex, updatedState)

    internal fun updateExerciseChildItem(
        position: ContainerPosition.Exercise,
        update: (ExerciseChildItem) -> ExerciseChildItem
    ): WorkoutStateMachine = withSequence(
        WorkoutStateSequenceOps.updateExerciseChildItem(stateSequence, position, update),
        currentIndex
    )

    internal fun updateSupersetChildStates(
        position: ContainerPosition.Superset,
        update: (MutableList<WorkoutState>) -> MutableList<WorkoutState>
    ): WorkoutStateMachine = withSequence(
        WorkoutStateSequenceOps.updateSupersetChildStates(stateSequence, position, update),
        currentIndex
    )

    /**
     * Progress to the next state if possible.
     */
    fun next(): WorkoutStateMachine {
        if (isCompleted) {
            return this
        }

        val nextIndex = currentIndex + 1
        require(nextIndex < allStates.size) { "Cannot advance beyond last state" }
        return WorkoutStateMachine(stateSequence, nextIndex, timeProvider)
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
     * Skip states until the predicate matches or we reach the last state.
     * Returns a new machine positioned at the matching state (or last state if no match).
     */
    fun skipUntil(predicate: (WorkoutState) -> Boolean): WorkoutStateMachine {
        var targetIndex = currentIndex + 1

        while (targetIndex < allStates.size) {
            val state = allStates[targetIndex]
            if (predicate(state)) {
                return WorkoutStateMachine(stateSequence, targetIndex, timeProvider)
            }
            targetIndex++
        }

        // If we reach here, we're at the last state.
        return WorkoutStateMachine(stateSequence, allStates.size - 1, timeProvider)
    }

    internal fun findPreviousIndex(
        fromIndexExclusive: Int = currentIndex,
        predicate: (WorkoutState) -> Boolean
    ): Int? = WorkoutStateQueries.findPreviousIndex(this, fromIndexExclusive, predicate)

    internal fun findPreviousNonRestIndex(fromIndexExclusive: Int = currentIndex): Int? =
        findPreviousIndex(fromIndexExclusive) { !it.isRestLike() }

    internal fun findPreviousSetIndex(
        excludedSetId: UUID?,
        fromIndexExclusive: Int = currentIndex,
        skipCalibration: Boolean = true
    ): Int? = findPreviousIndex(fromIndexExclusive) { state ->
        val setState = state as? WorkoutState.Set ?: return@findPreviousIndex false
        if (skipCalibration && setState.isCalibrationSet) return@findPreviousIndex false
        excludedSetId == null || setState.set.id != excludedSetId
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
                                val flatSize = WorkoutStateSequenceOps.flattenExerciseContainer(container).size
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
                            val flatSize = WorkoutStateSequenceOps.flattenExerciseContainer(container).size
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

    internal fun getFlatIndexInContainer(position: ContainerPosition.Exercise): Int? {
        val seqItem = stateSequence.getOrNull(position.containerSeqIndex) ?: return null
        val container = (seqItem as? WorkoutStateSequenceItem.Container)?.container
        if (container !is WorkoutStateContainer.ExerciseState) return null
        val prefixCount = container.childItems
            .take(position.childItemIndex)
            .sumOf { child ->
                when (child) {
                    is ExerciseChildItem.Normal -> 1
                    is ExerciseChildItem.CalibrationExecutionBlock -> child.childStates.size
                    is ExerciseChildItem.LoadSelectionBlock -> child.childStates.size
                    is ExerciseChildItem.UnilateralSetBlock -> child.childStates.size
                }
            }
        return prefixCount + position.indexWithinChildItem
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
                                WorkoutStateSequenceOps.flattenExerciseContainer(container)
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
                                    is WorkoutState.AutoRegulationRIRSelection -> state.exerciseId == exerciseId
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
                        is WorkoutStateContainer.ExerciseState -> WorkoutStateSequenceOps.flattenExerciseContainer(container).size
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

}

