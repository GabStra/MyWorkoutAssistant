package com.gabstra.myworkoutassistant.shared.stores

import com.gabstra.myworkoutassistant.shared.SetHistory
import kotlinx.coroutines.flow.StateFlow
import java.util.UUID

/**
 * Interface for managing executed set history with thread-safe mutations
 * and immutable snapshots exposed via StateFlow.
 */
interface ExecutedSetStore {
    /**
     * Immutable snapshot of all executed sets as a StateFlow.
     * Consumers should collect this flow or read .value for snapshots.
     */
    val executedSets: StateFlow<List<SetHistory>>

    /**
     * Replace all executed sets with a new list.
     */
    suspend fun replaceAll(newItems: List<SetHistory>)

    /**
     * Clear all executed sets.
     */
    suspend fun clear()

    /**
     * Upsert a set history entry. If an entry matching the predicate exists,
     * it will be updated (preserving id and incrementing version).
     * Otherwise, the new entry will be added.
     *
     * @param newSetHistory The new or updated set history entry
     * @param key A predicate function that identifies matching entries
     */
    suspend fun upsert(
        newSetHistory: SetHistory,
        key: (SetHistory) -> Boolean
    )

    /**
     * Remove the last element from the list if it's not empty.
     */
    suspend fun removeLastIfAny()

    /**
     * Get all executed sets for a specific exercise ID.
     * This is a convenience method that filters the current snapshot.
     */
    fun getAllByExerciseId(exerciseId: UUID): List<SetHistory> {
        return executedSets.value.filter { it.exerciseId == exerciseId }
    }
}

