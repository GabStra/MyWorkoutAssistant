package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.equipments.Equipment

data class WorkoutStore(
    val workouts: List<Workout> = emptyList(),
    val equipments: List<Equipment> = emptyList(), // List of available equipment
    val polarDeviceId: String? = null,
    val birthDateYear: Int,
    val weightKg: Double,
)