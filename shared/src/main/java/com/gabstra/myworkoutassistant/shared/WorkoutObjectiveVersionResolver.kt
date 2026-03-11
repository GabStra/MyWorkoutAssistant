package com.gabstra.myworkoutassistant.shared

import java.time.LocalDate
import java.util.UUID

/**
 * Resolves the effective workout version per workout family (globalId) for a given week.
 * Used so the weekly objective (timesCompletedInAWeek) shown in the calendar for a past week
 * reflects the version that was active during that week, not the current active version.
 *
 * Rule: for each globalId, select the latest workout version (by creationDate) whose
 * creationDate is on or before [weekEnd]. Multiple weeks can thus refer to the same
 * version until an edit creates a new one.
 */
object WorkoutObjectiveVersionResolver {

    /**
     * Returns a map from globalId to the workout version that defines the weekly objective
     * for the week ending on [weekEnd]. Only includes workouts that are enabled and have
     * a non-null, non-zero timesCompletedInAWeek.
     *
     * @param workouts All workout versions (including inactive) from the store
     * @param weekEnd End date of the selected week (inclusive)
     * @return Map from globalId to the effective Workout for that week
     */
    fun effectiveObjectiveVersionsForWeek(
        workouts: List<Workout>,
        weekEnd: LocalDate
    ): Map<UUID, Workout> {
        val eligible = workouts.filter {
            it.enabled &&
                it.timesCompletedInAWeek != null &&
                it.timesCompletedInAWeek != 0
        }
        val byGlobalId = eligible.groupBy { it.globalId }
        return byGlobalId.mapValues { (_, versions) ->
            // Latest version created on or before weekEnd; if none, use earliest version (edge case)
            val onOrBefore = versions.filter { it.creationDate <= weekEnd }
                .maxByOrNull { it.creationDate }
            onOrBefore ?: versions.minByOrNull { it.creationDate }!!
        }
    }
}
