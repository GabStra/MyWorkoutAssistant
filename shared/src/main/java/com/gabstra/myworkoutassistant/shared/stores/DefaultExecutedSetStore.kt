package com.gabstra.myworkoutassistant.shared.stores

import com.gabstra.myworkoutassistant.shared.SetHistory
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * Default implementation of ExecutedSetStore using MutableStateFlow and Mutex
 * for thread-safe mutations.
 */
class DefaultExecutedSetStore : ExecutedSetStore {
    private val _executedSets = MutableStateFlow<List<SetHistory>>(emptyList())
    override val executedSets = _executedSets.asStateFlow()

    private val mutex = Mutex()

    override suspend fun replaceAll(newItems: List<SetHistory>) {
        mutex.withLock {
            _executedSets.value = newItems
        }
    }

    override suspend fun clear() {
        mutex.withLock {
            _executedSets.value = emptyList()
        }
    }

    override suspend fun upsert(
        newSetHistory: SetHistory,
        key: (SetHistory) -> Boolean
    ) {
        mutex.withLock {
            val currentList = _executedSets.value.toMutableList()
            val existingIndex = currentList.indexOfFirst(key)

            if (existingIndex != -1) {
                // Update existing entry: preserve id and increment version
                val existing = currentList[existingIndex]
                currentList[existingIndex] = newSetHistory.copy(
                    id = existing.id,
                    version = existing.version.inc()
                )
            } else {
                // Add new entry
                currentList.add(newSetHistory)
            }

            _executedSets.value = currentList
        }
    }

    override suspend fun removeLastIfAny() {
        mutex.withLock {
            val currentList = _executedSets.value.toMutableList()
            if (currentList.isNotEmpty()) {
                currentList.removeAt(currentList.size - 1)
                _executedSets.value = currentList
            }
        }
    }
}

