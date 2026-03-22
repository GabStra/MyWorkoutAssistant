package com.gabstra.myworkoutassistant.shared.stores

import com.gabstra.myworkoutassistant.shared.RestHistory
import kotlinx.coroutines.flow.StateFlow
import java.util.UUID

/**
 * In-session buffer for [RestHistory] rows, mirroring [ExecutedSetStore].
 */
interface ExecutedRestStore {
    val executedRests: StateFlow<List<RestHistory>>

    suspend fun replaceAll(newItems: List<RestHistory>)

    suspend fun clear()

    suspend fun upsert(
        newRestHistory: RestHistory,
        key: (RestHistory) -> Boolean
    )

    fun getAllByExerciseId(exerciseId: UUID): List<RestHistory> {
        return executedRests.value.filter { it.exerciseId == exerciseId }
    }
}
