package com.gabstra.myworkoutassistant.shared

data class WorkoutStore(
    val workouts: List<Workout>, // List of exercises or exercise groups
    val polarDeviceId: String? = null,
    val birthDateYear: Int,
    val weightKg: Float,
)