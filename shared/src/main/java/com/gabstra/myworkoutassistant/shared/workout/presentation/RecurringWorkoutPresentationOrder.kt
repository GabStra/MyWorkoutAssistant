package com.gabstra.myworkoutassistant.shared.workout.presentation

import com.gabstra.myworkoutassistant.shared.Workout
import java.util.UUID

/** Keeps recurring prescriptions together at their first list position and in prescription order. */
fun orderWorkoutsForPresentation(workouts: List<Workout>): List<Workout> {
    val groups = linkedMapOf<Pair<Boolean, UUID>, MutableList<Pair<Int, Workout>>>()
    workouts.forEachIndexed { index, workout ->
        val key = workout.recurringSessionId?.let { true to it } ?: (false to workout.id)
        groups.getOrPut(key) { mutableListOf() }.add(index to workout)
    }
    return groups.values.flatMap { group ->
        if (group.first().second.recurringSessionId == null) group.map { it.second }
        else group.sortedWith(
            compareBy<Pair<Int, Workout>> { it.second.prescriptionOrdinal ?: Int.MAX_VALUE }
                .thenBy { it.first }
        ).map { it.second }
    }
}
