package com.gabstra.myworkoutassistant.shared

fun WorkoutStore.findWorkoutForHistory(workoutHistory: WorkoutHistory): Workout? {
    return workouts.find { it.id == workoutHistory.workoutId }
        ?: workouts.find { it.globalId == workoutHistory.globalId }
}
