package com.gabstra.myworkoutassistant.shared.workout.presentation

import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.sortedLatestFirst
import com.gabstra.myworkoutassistant.shared.workout.model.isNormallyCompleted
import java.util.UUID

/**
 * Pure next-prescription guidance for one recurring family.
 *
 * All workout ids reference the current [Workout.id] (the row the UI launches), never the
 * cross-version [Workout.globalId]. The helper keeps no cursor and does not mark skipped steps as
 * completed: it points at the first prescription in the current list order without a normally
 * completed history.
 */
data class RecurringPrescriptionProgress(
    val recurringSessionId: UUID,
    val lastCompletedWorkoutId: UUID?,
    val suggestedWorkoutId: UUID?,
    val reachedEnd: Boolean,
    val firstWorkoutId: UUID,
)

/**
 * Resolves the next prescribed workout for every explicit recurring family in [workouts].
 *
 * [workouts] must contain only the active current versions shown by the UI; no database lookup is
 * performed here. Families are keyed only by the explicit [Workout.recurringSessionId], never by
 * names. Within a family, duplicate global ids are collapsed with a stable first-occurrence rule so
 * a supplied older version cannot create a second step.
 *
 * A prescription counts as completed only when a normally completed history's
 * [WorkoutHistory.globalId] belongs to it. Histories with a null
 * [WorkoutHistory.recurringSessionId] (legacy snapshots) are accepted when the global id matches;
 * histories explicitly tagged with a different recurring session are rejected even if their global
 * id matches (detached or reassigned scope). Completion remains attached to the prescription when
 * the family list is reordered.
 */
fun resolveRecurringPrescriptionProgress(
    workouts: List<Workout>,
    histories: List<WorkoutHistory>,
): Map<UUID, RecurringPrescriptionProgress> {
    val families = workouts
        .withIndex()
        .mapNotNull { (index, workout) ->
            workout.recurringSessionId?.let { sessionId -> sessionId to (index to workout) }
        }
        .groupBy({ it.first }, { it.second })
        .mapValues { (_, entries) -> orderFamily(entries) }

    return families.mapValues { (sessionId, family) ->
        resolveFamilyProgress(sessionId, family, histories)
    }
}

private fun orderFamily(entries: List<Pair<Int, Workout>>): List<Workout> {
    val currentVersions = entries
        .sortedBy { it.first }
        .map { it.second }
        .distinctBy { it.globalId }
    return orderWorkoutsForPresentation(currentVersions)
}

private fun resolveFamilyProgress(
    sessionId: UUID,
    family: List<Workout>,
    histories: List<WorkoutHistory>,
): RecurringPrescriptionProgress {
    val firstWorkoutId = family.first().id
    val historiesForFamily = histories
        .filter { history ->
            history.isNormallyCompleted() &&
                family.any { it.globalId == history.globalId } &&
                (history.recurringSessionId == null || history.recurringSessionId == sessionId)
        }
        .sortedLatestFirst()
    val latestCompleted = historiesForFamily.firstOrNull()
    val completedGlobalIds = historiesForFamily.mapTo(mutableSetOf()) { it.globalId }
    val nextWorkout = family.firstOrNull { it.globalId !in completedGlobalIds }
    val lastCompletedWorkout = latestCompleted?.let { history ->
        family.firstOrNull { it.globalId == history.globalId }
    }
    return RecurringPrescriptionProgress(
        recurringSessionId = sessionId,
        lastCompletedWorkoutId = lastCompletedWorkout?.id,
        suggestedWorkoutId = nextWorkout?.id,
        reachedEnd = nextWorkout == null,
        firstWorkoutId = firstWorkoutId,
    )
}
