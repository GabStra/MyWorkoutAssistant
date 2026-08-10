package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.equipments.AccessoryEquipment
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment

data class WorkoutStore(
    val schemaVersion: Int = CURRENT_SCHEMA_VERSION,
    val exerciseDefinitions: List<ExerciseDefinition> = emptyList(),
    val workouts: List<Workout> = emptyList(),
    val equipments: List<WeightLoadedEquipment> = emptyList(), // List of available equipment
    val accessoryEquipments: List<AccessoryEquipment> = emptyList(), // List of accessory equipment
    val workoutPlans: List<WorkoutPlan> = emptyList(),
    val weeklyProgressOverrides: List<WeeklyProgressOverride> = emptyList(),
    val externalHeartRateConfigs: List<ExternalHeartRateConfig> = emptyList(),
    val birthDateYear: Int,
    val weightKg: Double,
    val progressionPercentageAmount: Double,
    val measuredMaxHeartRate: Int? = null,
    val restingHeartRate: Int? = null,
    val deloadConfig: DeloadConfig = DeloadConfig(),
) {
    companion object {
        const val CURRENT_SCHEMA_VERSION = 3
    }
}
