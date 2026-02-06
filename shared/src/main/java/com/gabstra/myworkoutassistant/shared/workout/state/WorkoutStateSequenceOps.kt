package com.gabstra.myworkoutassistant.shared.workout.state

internal object WorkoutStateSequenceOps {
    fun flattenChildItems(childItems: List<ExerciseChildItem>): List<WorkoutState> = childItems.flatMap { item ->
        when (item) {
            is ExerciseChildItem.Normal -> listOf(item.state)
            is ExerciseChildItem.CalibrationExecutionBlock -> item.childStates
            is ExerciseChildItem.LoadSelectionBlock -> item.childStates
            is ExerciseChildItem.UnilateralSetBlock -> item.childStates
        }
    }

    fun flattenExerciseContainer(container: WorkoutStateContainer.ExerciseState): List<WorkoutState> =
        flattenChildItems(container.childItems)

    fun flattenSequence(sequence: List<WorkoutStateSequenceItem>): List<WorkoutState> = buildList {
        sequence.forEach { item ->
            when (item) {
                is WorkoutStateSequenceItem.Container -> {
                    when (val container = item.container) {
                        is WorkoutStateContainer.ExerciseState -> addAll(flattenExerciseContainer(container))
                        is WorkoutStateContainer.SupersetState -> addAll(container.childStates)
                    }
                }
                is WorkoutStateSequenceItem.RestBetweenExercises -> add(item.rest)
            }
        }
    }

    fun mapSequenceStates(
        sequence: List<WorkoutStateSequenceItem>,
        mapState: (WorkoutState) -> WorkoutState
    ): List<WorkoutStateSequenceItem> = sequence.map { item ->
        when (item) {
            is WorkoutStateSequenceItem.Container -> {
                when (val container = item.container) {
                    is WorkoutStateContainer.ExerciseState -> {
                        val updatedItems = container.childItems.map { childItem ->
                            when (childItem) {
                                is ExerciseChildItem.Normal ->
                                    ExerciseChildItem.Normal(mapState(childItem.state))
                                is ExerciseChildItem.CalibrationExecutionBlock ->
                                    ExerciseChildItem.CalibrationExecutionBlock(
                                        childItem.childStates.map(mapState).toMutableList()
                                    )
                                is ExerciseChildItem.LoadSelectionBlock ->
                                    ExerciseChildItem.LoadSelectionBlock(
                                        childItem.childStates.map(mapState).toMutableList()
                                    )
                                is ExerciseChildItem.UnilateralSetBlock ->
                                    ExerciseChildItem.UnilateralSetBlock(
                                        childItem.childStates.map(mapState).toMutableList()
                                    )
                            }
                        }.toMutableList()
                        WorkoutStateSequenceItem.Container(container.copy(childItems = updatedItems))
                    }
                    is WorkoutStateContainer.SupersetState -> {
                        val updatedChildStates = container.childStates.map(mapState).toMutableList()
                        WorkoutStateSequenceItem.Container(container.copy(childStates = updatedChildStates))
                    }
                }
            }
            is WorkoutStateSequenceItem.RestBetweenExercises -> {
                val updatedRest = mapState(item.rest) as WorkoutState.Rest
                WorkoutStateSequenceItem.RestBetweenExercises(updatedRest)
            }
        }
    }

    fun mapSequenceStatesIndexed(
        sequence: List<WorkoutStateSequenceItem>,
        mapState: (Int, WorkoutState) -> WorkoutState
    ): List<WorkoutStateSequenceItem> {
        var flatIndex = 0
        return sequence.map { item ->
            when (item) {
                is WorkoutStateSequenceItem.Container -> {
                    when (val container = item.container) {
                        is WorkoutStateContainer.ExerciseState -> {
                            val updatedItems = container.childItems.map { childItem ->
                                when (childItem) {
                                    is ExerciseChildItem.Normal -> {
                                        val mapped = mapState(flatIndex, childItem.state)
                                        flatIndex++
                                        ExerciseChildItem.Normal(mapped)
                                    }
                                    is ExerciseChildItem.CalibrationExecutionBlock -> {
                                        val mappedStates = childItem.childStates.map { state ->
                                            val mapped = mapState(flatIndex, state)
                                            flatIndex++
                                            mapped
                                        }.toMutableList()
                                        ExerciseChildItem.CalibrationExecutionBlock(mappedStates)
                                    }
                                    is ExerciseChildItem.LoadSelectionBlock -> {
                                        val mappedStates = childItem.childStates.map { state ->
                                            val mapped = mapState(flatIndex, state)
                                            flatIndex++
                                            mapped
                                        }.toMutableList()
                                        ExerciseChildItem.LoadSelectionBlock(mappedStates)
                                    }
                                    is ExerciseChildItem.UnilateralSetBlock -> {
                                        val mappedStates = childItem.childStates.map { state ->
                                            val mapped = mapState(flatIndex, state)
                                            flatIndex++
                                            mapped
                                        }.toMutableList()
                                        ExerciseChildItem.UnilateralSetBlock(mappedStates)
                                    }
                                }
                            }.toMutableList()
                            WorkoutStateSequenceItem.Container(container.copy(childItems = updatedItems))
                        }
                        is WorkoutStateContainer.SupersetState -> {
                            val mappedStates = container.childStates.map { state ->
                                val mapped = mapState(flatIndex, state)
                                flatIndex++
                                mapped
                            }.toMutableList()
                            WorkoutStateSequenceItem.Container(container.copy(childStates = mappedStates))
                        }
                    }
                }
                is WorkoutStateSequenceItem.RestBetweenExercises -> {
                    val mapped = mapState(flatIndex, item.rest) as WorkoutState.Rest
                    flatIndex++
                    WorkoutStateSequenceItem.RestBetweenExercises(mapped)
                }
            }
        }
    }

    fun updateStateAtFlatIndex(
        sequence: List<WorkoutStateSequenceItem>,
        flatIndex: Int,
        updatedState: WorkoutState
    ): List<WorkoutStateSequenceItem> {
        var currentFlatPos = 0
        return sequence.map { item ->
            when (item) {
                is WorkoutStateSequenceItem.Container -> {
                    when (val container = item.container) {
                        is WorkoutStateContainer.ExerciseState -> {
                            val flatStates = flattenExerciseContainer(container)
                            val updatedFlat = flatStates.mapIndexed { idx, state ->
                                if (currentFlatPos + idx == flatIndex) updatedState else state
                            }
                            currentFlatPos += flatStates.size
                            val updatedChildItems = rebuildExerciseChildItemsFromFlat(
                                container.childItems,
                                updatedFlat
                            )
                            WorkoutStateSequenceItem.Container(container.copy(childItems = updatedChildItems))
                        }
                        is WorkoutStateContainer.SupersetState -> {
                            val updatedChildStates = container.childStates.mapIndexed { idx, state ->
                                if (currentFlatPos + idx == flatIndex) updatedState else state
                            }.toMutableList()
                            currentFlatPos += container.childStates.size
                            WorkoutStateSequenceItem.Container(container.copy(childStates = updatedChildStates))
                        }
                    }
                }
                is WorkoutStateSequenceItem.RestBetweenExercises -> {
                    val result = if (currentFlatPos == flatIndex) {
                        WorkoutStateSequenceItem.RestBetweenExercises(updatedState as WorkoutState.Rest)
                    } else {
                        item
                    }
                    currentFlatPos++
                    result
                }
            }
        }
    }

    fun updateExerciseChildItem(
        sequence: List<WorkoutStateSequenceItem>,
        position: ContainerPosition.Exercise,
        update: (ExerciseChildItem) -> ExerciseChildItem
    ): List<WorkoutStateSequenceItem> = sequence.mapIndexed { seqIdx, seqItem ->
        if (seqIdx != position.containerSeqIndex || seqItem !is WorkoutStateSequenceItem.Container) {
            seqItem
        } else {
            val container = seqItem.container
            if (container is WorkoutStateContainer.ExerciseState) {
                val newChildItems = container.childItems.toMutableList()
                val original = newChildItems.getOrNull(position.childItemIndex)
                if (original != null) {
                    newChildItems[position.childItemIndex] = update(original)
                    WorkoutStateSequenceItem.Container(container.copy(childItems = newChildItems))
                } else {
                    seqItem
                }
            } else {
                seqItem
            }
        }
    }

    fun updateSupersetChildStates(
        sequence: List<WorkoutStateSequenceItem>,
        position: ContainerPosition.Superset,
        update: (MutableList<WorkoutState>) -> MutableList<WorkoutState>
    ): List<WorkoutStateSequenceItem> = sequence.mapIndexed { seqIdx, item ->
        if (seqIdx != position.containerSeqIndex || item !is WorkoutStateSequenceItem.Container) {
            item
        } else {
            val container = item.container
            if (container is WorkoutStateContainer.SupersetState) {
                val updatedChildStates = update(container.childStates.toMutableList())
                WorkoutStateSequenceItem.Container(container.copy(childStates = updatedChildStates))
            } else {
                item
            }
        }
    }

    fun mapStatesForExercise(
        sequence: List<WorkoutStateSequenceItem>,
        exerciseId: java.util.UUID,
        mapper: (WorkoutState) -> WorkoutState
    ): List<WorkoutStateSequenceItem> = mapSequenceStates(sequence) { state ->
        if (state.exerciseIdOrNull() == exerciseId) mapper(state) else state
    }

    fun replaceStatesById(
        sequence: List<WorkoutStateSequenceItem>,
        idSelector: (WorkoutState) -> java.util.UUID?,
        replacements: Map<java.util.UUID, WorkoutState>
    ): List<WorkoutStateSequenceItem> = mapSequenceStates(sequence) { state ->
        val id = idSelector(state)
        if (id != null) replacements[id] ?: state else state
    }

    fun rebuildExerciseChildItemsFromFlat(
        childItems: MutableList<ExerciseChildItem>,
        flatStates: List<WorkoutState>
    ): MutableList<ExerciseChildItem> {
        val updatedChildItems = mutableListOf<ExerciseChildItem>()
        var index = 0
        for (item in childItems) {
            when (item) {
                is ExerciseChildItem.Normal -> {
                    updatedChildItems.add(ExerciseChildItem.Normal(flatStates[index++]))
                }
                is ExerciseChildItem.CalibrationExecutionBlock -> {
                    val size = item.childStates.size
                    updatedChildItems.add(
                        ExerciseChildItem.CalibrationExecutionBlock(
                            flatStates.subList(index, index + size).toMutableList()
                        )
                    )
                    index += size
                }
                is ExerciseChildItem.LoadSelectionBlock -> {
                    val size = item.childStates.size
                    updatedChildItems.add(
                        ExerciseChildItem.LoadSelectionBlock(
                            flatStates.subList(index, index + size).toMutableList()
                        )
                    )
                    index += size
                }
                is ExerciseChildItem.UnilateralSetBlock -> {
                    val size = item.childStates.size
                    updatedChildItems.add(
                        ExerciseChildItem.UnilateralSetBlock(
                            flatStates.subList(index, index + size).toMutableList()
                        )
                    )
                    index += size
                }
            }
        }
        return updatedChildItems
    }
}

