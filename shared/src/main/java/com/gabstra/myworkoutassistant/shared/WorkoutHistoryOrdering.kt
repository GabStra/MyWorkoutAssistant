package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.workout.history.knownStartTimeOrNull

/**
 * Newest-first session order. The calendar date is always known, so it is the
 * primary key; a session whose time is unknown is ordered with the date only and
 * placed after known-time sessions on the same day rather than fabricating a
 * midnight timestamp. For known-time records this is equivalent to ordering by
 * [WorkoutHistory.startTime].
 */
val latestWorkoutHistoryComparator: Comparator<WorkoutHistory> =
    compareByDescending<WorkoutHistory> { it.date }
        .thenByDescending { it.knownStartTimeOrNull() != null }
        .thenByDescending { it.knownStartTimeOrNull() }
        .thenByDescending { it.version.toLong() }
        .thenByDescending { it.id.toString() }

fun Iterable<WorkoutHistory>.sortedLatestFirst(): List<WorkoutHistory> =
    sortedWith(latestWorkoutHistoryComparator)
