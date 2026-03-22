package com.gabstra.myworkoutassistant.shared.stores

import com.gabstra.myworkoutassistant.shared.RestHistory
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

class DefaultExecutedRestStore : ExecutedRestStore {
    private val _executedRests = MutableStateFlow<List<RestHistory>>(emptyList())
    override val executedRests = _executedRests.asStateFlow()

    private val mutex = Mutex()

    override suspend fun replaceAll(newItems: List<RestHistory>) {
        mutex.withLock {
            _executedRests.value = newItems
        }
    }

    override suspend fun clear() {
        mutex.withLock {
            _executedRests.value = emptyList()
        }
    }

    override suspend fun upsert(
        newRestHistory: RestHistory,
        key: (RestHistory) -> Boolean
    ) {
        mutex.withLock {
            val currentList = _executedRests.value.toMutableList()
            val existingIndex = currentList.indexOfFirst(key)

            if (existingIndex != -1) {
                val existing = currentList[existingIndex]
                currentList[existingIndex] = newRestHistory.copy(
                    id = existing.id,
                    version = existing.version.inc()
                )
            } else {
                currentList.add(newRestHistory)
            }

            _executedRests.value = currentList
        }
    }
}
