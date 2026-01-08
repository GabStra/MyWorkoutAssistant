package com.gabstra.myworkoutassistant.shared.adapters

import com.gabstra.myworkoutassistant.shared.WorkoutPlan
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.equipments.AccessoryEquipment
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.google.gson.*
import com.google.gson.reflect.TypeToken
import java.lang.reflect.Type

/**
 * Custom Gson adapter for WorkoutStore that ensures all list fields are never null.
 * This handles cases where Gson deserializes missing JSON fields as null instead of
 * using Kotlin default values.
 */
class WorkoutStoreAdapter : JsonDeserializer<WorkoutStore> {
    override fun deserialize(
        json: JsonElement,
        typeOfT: Type,
        context: JsonDeserializationContext
    ): WorkoutStore {
        val jsonObject = json.asJsonObject
        
        // Define TypeTokens for proper generic type deserialization
        val workoutsType = object : TypeToken<List<Workout>>() {}.type
        val equipmentsType = object : TypeToken<List<WeightLoadedEquipment>>() {}.type
        val accessoryEquipmentsType = object : TypeToken<List<AccessoryEquipment>>() {}.type
        val workoutPlansType = object : TypeToken<List<WorkoutPlan>>() {}.type
        
        // Safely get list fields, defaulting to empty lists if null or missing
        val workouts = jsonObject.get("workouts")?.let {
            if (it.isJsonNull) emptyList<Workout>() else context.deserialize(it, workoutsType)
        } ?: emptyList()
        
        val equipments = jsonObject.get("equipments")?.let {
            if (it.isJsonNull) emptyList<WeightLoadedEquipment>() else context.deserialize(it, equipmentsType)
        } ?: emptyList()
        
        val accessoryEquipments = jsonObject.get("accessoryEquipments")?.let {
            if (it.isJsonNull) emptyList<AccessoryEquipment>() else context.deserialize(it, accessoryEquipmentsType)
        } ?: emptyList()
        
        val workoutPlans = jsonObject.get("workoutPlans")?.let {
            if (it.isJsonNull) emptyList<WorkoutPlan>() else context.deserialize(it, workoutPlansType)
        } ?: emptyList()
        
        val polarDeviceId = jsonObject.get("polarDeviceId")?.let {
            if (it.isJsonNull) null else it.asString
        }
        
        val birthDateYear = jsonObject.get("birthDateYear")?.asInt ?: 0
        val weightKg = jsonObject.get("weightKg")?.asDouble ?: 0.0
        val progressionPercentageAmount = jsonObject.get("progressionPercentageAmount")?.asDouble ?: 0.0
        
        return WorkoutStore(
            workouts = workouts,
            equipments = equipments,
            accessoryEquipments = accessoryEquipments,
            workoutPlans = workoutPlans,
            polarDeviceId = polarDeviceId,
            birthDateYear = birthDateYear,
            weightKg = weightKg,
            progressionPercentageAmount = progressionPercentageAmount
        )
    }
}
