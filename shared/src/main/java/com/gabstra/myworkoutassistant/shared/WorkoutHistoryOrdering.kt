package com.gabstra.myworkoutassistant.shared

val latestWorkoutHistoryComparator: Comparator<WorkoutHistory> =
    compareByDescending<WorkoutHistory> { it.startTime }
        .thenByDescending { it.version.toLong() }
        .thenByDescending { it.time }
        .thenByDescending { it.date }
        .thenByDescending { it.id.toString() }

fun Iterable<WorkoutHistory>.sortedLatestFirst(): List<WorkoutHistory> =
    sortedWith(latestWorkoutHistoryComparator)
