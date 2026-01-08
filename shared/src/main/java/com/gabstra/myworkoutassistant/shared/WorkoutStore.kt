package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.equipments.AccessoryEquipment
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment

data class WorkoutStore(
    val workouts: List<Workout> = emptyList(),
    val equipments: List<WeightLoadedEquipment> = emptyList(), // List of available equipment
    val accessoryEquipments: List<AccessoryEquipment> = emptyList(), // List of accessory equipment
    val workoutPlans: List<WorkoutPlan> = emptyList(),
    val polarDeviceId: String? = null,
    val birthDateYear: Int,
    val weightKg: Double,
    val progressionPercentageAmount: Double,
)