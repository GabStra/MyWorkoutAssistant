package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
import java.util.UUID

data class SessionSetSnapshot(
    val setId: UUID,
    val set: Set,
    val simpleSet: SimpleSet? = null,
    val wasExecuted: Boolean = false,
    val wasSkipped: Boolean = false,
)

data class ExerciseSessionSnapshot(
    val sets: List<SessionSetSnapshot> = emptyList(),
) {
    fun isEmpty(): Boolean = sets.isEmpty()

    fun isNotEmpty(): Boolean = sets.isNotEmpty()
}
