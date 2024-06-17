package com.gabstra.myworkoutassistant.data

enum class Screen(val route: String) {
    WorkoutSelection("workoutSelection"),
    WorkoutDetail("workoutDetail"),
    Workout("workout"),
    Exercise("exercise"),
    Rest("Rest"),
    WorkoutComplete("workoutComplete"),
    Loading("workoutSelection"),
}