package com.gabstra.myworkoutassistant.shared.export

import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutPlan
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.adapters.AccessoryEquipmentAdapter
import com.gabstra.myworkoutassistant.shared.adapters.EquipmentAdapter
import com.gabstra.myworkoutassistant.shared.equipments.AccessoryEquipment
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbell
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbells
import com.gabstra.myworkoutassistant.shared.equipments.Generic
import com.gabstra.myworkoutassistant.shared.equipments.Machine
import com.gabstra.myworkoutassistant.shared.equipments.PlateLoadedCable
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.equipments.WeightVest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import com.google.gson.GsonBuilder
import com.google.gson.JsonObject
import java.util.UUID

/**
 * Extracts equipment IDs from a list of workouts.
 * 
 * @param workouts List of workouts to extract equipment from
 * @return Pair of (equipment IDs set, accessory equipment IDs set)
 */
private fun extractEquipmentIdsFromWorkouts(workouts: List<Workout>): Pair<Set<UUID>, Set<UUID>> {
    val equipmentIds = mutableSetOf<UUID>()
    val accessoryEquipmentIds = mutableSetOf<UUID>()
    
    workouts.forEach { workout ->
        workout.workoutComponents.forEach { component ->
            when (component) {
                is Exercise -> {
                    component.equipmentId?.let { equipmentIds.add(it) }
                    component.requiredAccessoryEquipmentIds?.forEach { accessoryEquipmentIds.add(it) }
                }
                is Superset -> {
                    component.exercises.forEach { exercise ->
                        exercise.equipmentId?.let { equipmentIds.add(it) }
                        exercise.requiredAccessoryEquipmentIds?.forEach { accessoryEquipmentIds.add(it) }
                    }
                }
                else -> {
                    // Rest or other components don't have equipment
                }
            }
        }
    }
    
    return Pair(equipmentIds, accessoryEquipmentIds)
}

/**
 * Extracts equipment from workouts specified by their IDs.
 * 
 * @param workoutStore The workout store containing all workouts and equipment
 * @param workoutIds List of workout IDs to extract equipment from
 * @return Pair of (filtered equipment list, filtered accessory equipment list)
 */
fun extractEquipmentFromWorkouts(
    workoutStore: WorkoutStore,
    workoutIds: List<UUID>
): Pair<List<WeightLoadedEquipment>, List<AccessoryEquipment>> {
    val workouts = workoutStore.workouts.filter { it.id in workoutIds }
    val (equipmentIds, accessoryEquipmentIds) = extractEquipmentIdsFromWorkouts(workouts)
    
    val filteredEquipments = workoutStore.equipments.filter { it.id in equipmentIds }
    val filteredAccessoryEquipments = workoutStore.accessoryEquipments.filter { it.id in accessoryEquipmentIds }
    
    return Pair(filteredEquipments, filteredAccessoryEquipments)
}

/**
 * Extracts equipment from a workout plan or all workouts.
 * 
 * @param workoutStore The workout store containing all workouts and equipment
 * @param planId The workout plan ID to extract equipment from, or null to extract from all workouts
 * @return Pair of (filtered equipment list, filtered accessory equipment list)
 */
fun extractEquipmentFromWorkoutPlan(
    workoutStore: WorkoutStore,
    planId: UUID?
): Pair<List<WeightLoadedEquipment>, List<AccessoryEquipment>> {
    val workoutIds = if (planId != null) {
        val plan = workoutStore.workoutPlans.find { it.id == planId }
        plan?.workoutIds ?: emptyList()
    } else {
        // Extract from all workouts
        workoutStore.workouts.map { it.id }
    }
    
    return extractEquipmentFromWorkouts(workoutStore, workoutIds)
}

/**
 * Converts equipment lists to JSON format required by workout_generator.py.
 * 
 * The JSON format is:
 * {
 *   "equipments": [...],
 *   "accessoryEquipments": [...]
 * }
 * 
 * @param equipments List of weight-loaded equipment
 * @param accessoryEquipments List of accessory equipment
 * @return JSON string representation
 */
fun equipmentToJSON(
    equipments: List<WeightLoadedEquipment>,
    accessoryEquipments: List<AccessoryEquipment>
): String {
    val gson = GsonBuilder()
        .registerTypeAdapter(Generic::class.java, EquipmentAdapter())
        .registerTypeAdapter(Dumbbells::class.java, EquipmentAdapter())
        .registerTypeAdapter(Dumbbell::class.java, EquipmentAdapter())
        .registerTypeAdapter(Machine::class.java, EquipmentAdapter())
        .registerTypeAdapter(PlateLoadedCable::class.java, EquipmentAdapter())
        .registerTypeAdapter(Barbell::class.java, EquipmentAdapter())
        .registerTypeAdapter(WeightVest::class.java, EquipmentAdapter())
        .registerTypeAdapter(AccessoryEquipment::class.java, AccessoryEquipmentAdapter())
        .create()
    
    val jsonObject = JsonObject()
    jsonObject.add("equipments", gson.toJsonTree(equipments))
    jsonObject.add("accessoryEquipments", gson.toJsonTree(accessoryEquipments))
    
    return gson.toJson(jsonObject)
}
