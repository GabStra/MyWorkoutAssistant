package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.equipments.AccessoryEquipment
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment

data class WorkoutPlanPackage(
    val name: String,
    val workouts: List<Workout> = emptyList(),
    val equipments: List<WeightLoadedEquipment> = emptyList(),
    val accessoryEquipments: List<AccessoryEquipment> = emptyList(),
)
