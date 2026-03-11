package com.gabstra.myworkoutassistant.shared

import java.time.LocalDate
import java.util.UUID

data class WeeklyProgressSnapshot(
    val weeklyWorkoutsByActualTarget: Map<Workout, Pair<Int, Int>> = emptyMap(),
    val objectiveProgress: Double = 0.0,
    val eligibleWorkouts: List<Workout> = emptyList(),
    val includedWorkoutGlobalIds: Set<UUID> = emptySet(),
    val hasOverride: Boolean = false,
) {
    val excludedWorkoutGlobalIds: Set<UUID>
        get() = if (!hasOverride) {
            emptySet()
        } else {
            eligibleWorkouts.asSequence()
                .map { it.globalId }
                .toSet() - includedWorkoutGlobalIds
        }
}

object WeeklyProgressResolver {
    fun resolveForWeek(
        workouts: List<Workout>,
        workoutHistoriesInWeek: List<WorkoutHistory>,
        weekEnd: LocalDate,
        weeklyProgressOverride: WeeklyProgressOverride?,
    ): WeeklyProgressSnapshot {
        val effectiveObjectiveWorkoutsByGlobalId =
            WorkoutObjectiveVersionResolver.effectiveObjectiveVersionsForWeek(
                workouts = workouts,
                weekEnd = weekEnd
            )

        if (effectiveObjectiveWorkoutsByGlobalId.isEmpty()) {
            return WeeklyProgressSnapshot(hasOverride = weeklyProgressOverride != null)
        }

        val eligibleWorkouts = effectiveObjectiveWorkoutsByGlobalId.values
            .sortedWith(compareBy<Workout> { it.order }.thenBy { it.id })
        val eligibleWorkoutGlobalIds = effectiveObjectiveWorkoutsByGlobalId.keys
        val includedWorkoutGlobalIds = if (weeklyProgressOverride != null) {
            weeklyProgressOverride.includedWorkoutGlobalIds
                .asSequence()
                .filter { it in eligibleWorkoutGlobalIds }
                .toSet()
        } else {
            eligibleWorkoutGlobalIds
        }

        val actualCountsByWorkoutId = workoutHistoriesInWeek
            .asSequence()
            .filter { it.isDone && it.globalId in includedWorkoutGlobalIds }
            .mapNotNull { history -> effectiveObjectiveWorkoutsByGlobalId[history.globalId] }
            .groupingBy { it.id }
            .eachCount()

        val weeklyWorkoutsByActualTarget = eligibleWorkouts
            .asSequence()
            .filter { it.globalId in includedWorkoutGlobalIds }
            .associateWith { workout ->
                val target = workout.timesCompletedInAWeek ?: 0
                val actual = actualCountsByWorkoutId[workout.id] ?: 0
                val countedActual = if (target <= 0 || actual >= target) {
                    actual
                } else {
                    minOf(actual, target)
                }
                countedActual to target
            }

        val objectiveProgress = if (weeklyWorkoutsByActualTarget.isNotEmpty()) {
            weeklyWorkoutsByActualTarget.values
                .map { (actual, target) ->
                    if (target > 0) actual.toDouble() / target else 0.0
                }
                .average()
        } else {
            0.0
        }

        return WeeklyProgressSnapshot(
            weeklyWorkoutsByActualTarget = weeklyWorkoutsByActualTarget,
            objectiveProgress = objectiveProgress,
            eligibleWorkouts = eligibleWorkouts,
            includedWorkoutGlobalIds = includedWorkoutGlobalIds,
            hasOverride = weeklyProgressOverride != null,
        )
    }
}
