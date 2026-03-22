package com.gabstra.myworkoutassistant.shared.workout.history

import com.gabstra.myworkoutassistant.shared.RestHistory
import com.gabstra.myworkoutassistant.shared.RestHistoryScope
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import java.time.LocalDateTime
import java.util.UUID

sealed class SessionTimelineItem {
    data class SetStep(val history: SetHistory) : SessionTimelineItem()
    data class RestStep(val history: RestHistory) : SessionTimelineItem()
}

/**
 * Merges set and rest histories for a single workout session in execution order.
 * Sort key: [executionSequence], then [startTime] (nulls last), then [id].
 */
fun mergeSessionTimeline(
    sets: List<SetHistory>,
    rests: List<RestHistory>
): List<SessionTimelineItem> {
    data class Tagged(
        val seq: Long,
        val startTime: LocalDateTime?,
        val id: UUID,
        val item: SessionTimelineItem
    )

    val tagged = mutableListOf<Tagged>()
    sets.forEach { s ->
        tagged.add(
            Tagged(
                seq = s.executionSequence?.toLong() ?: Long.MAX_VALUE,
                startTime = s.startTime,
                id = s.id,
                item = SessionTimelineItem.SetStep(s)
            )
        )
    }
    rests.forEach { r ->
        tagged.add(
            Tagged(
                seq = r.executionSequence?.toLong() ?: Long.MAX_VALUE,
                startTime = r.startTime,
                id = r.id,
                item = SessionTimelineItem.RestStep(r)
            )
        )
    }
    return tagged
        .sortedWith(
            compareBy<Tagged> { it.seq }
                .thenBy { it.startTime == null }
                .thenBy { it.startTime }
                .thenBy { it.id }
        )
        .map { it.item }
}

/**
 * [RestHistory] rows for top-level template [Rest] components (rest between workout components),
 * in [Workout.workoutComponents] order. Only rows with [RestHistory.scope] ==
 * [RestHistoryScope.BETWEEN_WORKOUT_COMPONENTS] and a non-null [RestHistory.workoutComponentId]
 * matching a template [Rest] id are included.
 *
 * **Invariant:** at most one row per template `Rest` id in a session. If more than one row
 * targets the same [RestHistory.workoutComponentId], throws [IllegalStateException].
 */
fun orderedBetweenWorkoutComponentRestHistories(
    allRestHistories: List<RestHistory>,
    workout: Workout
): List<RestHistory> {
    val between = allRestHistories.filter {
        it.scope == RestHistoryScope.BETWEEN_WORKOUT_COMPONENTS && it.workoutComponentId != null
    }
    if (between.isEmpty()) return emptyList()

    val byComponentId = between.groupBy { it.workoutComponentId!! }
    val ordered = mutableListOf<RestHistory>()

    for (component in workout.workoutComponents) {
        if (component !is Rest) continue
        val matches = byComponentId[component.id].orEmpty()
        when (matches.size) {
            0 -> { }
            1 -> ordered.add(matches.first())
            else -> {
                val sorted = matches.sortedWith(restHistorySessionComparator())
                throw IllegalStateException(
                    "Expected at most one RestHistory per template Rest (workoutComponentId=${component.id}), " +
                        "found ${sorted.size}: ${sorted.map { it.id }}"
                )
            }
        }
    }

    return ordered
}

private fun restHistorySessionComparator(): Comparator<RestHistory> =
    compareBy<RestHistory>(
        { it.executionSequence == null },
        { it.executionSequence ?: UInt.MAX_VALUE },
        { it.startTime == null },
        { it.startTime },
        { it.id }
    )
