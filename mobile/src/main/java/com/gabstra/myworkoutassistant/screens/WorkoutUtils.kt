package com.gabstra.myworkoutassistant.screens

import com.gabstra.myworkoutassistant.shared.MuscleGroup
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset

/**
 * Aggregates all muscle groups from all workouts.
 * Includes muscle groups from exercises and exercises within Supersets.
 */
fun aggregateAllMuscleGroups(workouts: List<Workout>): Set<MuscleGroup> {
    val allMuscleGroups = mutableSetOf<MuscleGroup>()

    workouts.forEach { workout ->
        workout.workoutComponents.forEach { component ->
            when (component) {
                is Exercise -> {
                    component.muscleGroups?.let { muscleGroups ->
                        allMuscleGroups.addAll(muscleGroups)
                    }
                }
                is Superset -> {
                    component.exercises.forEach { exercise ->
                        exercise.muscleGroups?.let { muscleGroups ->
                            allMuscleGroups.addAll(muscleGroups)
                        }
                    }
                }
                else -> { /* Rest or other components don't have muscle groups */ }
            }
        }
    }

    return allMuscleGroups
}
