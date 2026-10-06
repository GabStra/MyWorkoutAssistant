package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.equipments.AccessoryEquipment
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment

data class WorkoutPlanPackage(
    val name: String,
    val schemaVersion: Int = WorkoutStore.CURRENT_SCHEMA_VERSION,
    val exerciseDefinitions: List<ExerciseDefinition> = emptyList(),
    val workouts: List<Workout> = emptyList(),
    val equipments: List<WeightLoadedEquipment> = emptyList(),
    val accessoryEquipments: List<AccessoryEquipment> = emptyList(),
    val exerciseMovements: List<ExerciseMovementBackup> = emptyList(),
)
