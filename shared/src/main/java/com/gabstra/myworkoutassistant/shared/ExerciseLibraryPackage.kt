package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.equipments.AccessoryEquipment
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment

const val EXERCISE_LIBRARY_PACKAGE_FORMAT = "myworkoutassistant.exercise-library"

data class ExerciseLibraryPackage(
    val format: String = EXERCISE_LIBRARY_PACKAGE_FORMAT,
    val schemaVersion: Int = WorkoutStore.CURRENT_SCHEMA_VERSION,
    val exerciseDefinitions: List<ExerciseDefinition> = emptyList(),
    val equipments: List<WeightLoadedEquipment> = emptyList(),
    val accessoryEquipments: List<AccessoryEquipment> = emptyList(),
    val exerciseMovements: List<ExerciseMovementBackup> = emptyList(),
)
