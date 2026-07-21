package com.gabstra.myworkoutassistant.data

enum class Screen(val route: String) {
    WorkoutSelection("workoutSelection"),
    WorkoutDetail("workoutDetail"),
    WorkoutExercises("workoutExercises"),
    Workout("workout"),
    Loading("loading"),
}
