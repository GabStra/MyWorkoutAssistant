package com.gabstra.myworkoutassistant.shared.adapters

import com.gabstra.myworkoutassistant.shared.ExerciseMovementBackup
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutPlanPackage
import com.gabstra.myworkoutassistant.shared.equipments.AccessoryEquipment
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.google.gson.JsonDeserializationContext
import com.google.gson.JsonDeserializer
import com.google.gson.JsonElement
import com.google.gson.reflect.TypeToken
import java.lang.reflect.Type

class WorkoutPlanPackageAdapter : JsonDeserializer<WorkoutPlanPackage> {
    override fun deserialize(
        json: JsonElement,
        typeOfT: Type,
        context: JsonDeserializationContext
    ): WorkoutPlanPackage {
        val jsonObject = json.asJsonObject

        val workoutsType = object : TypeToken<List<Workout>>() {}.type
        val equipmentsType = object : TypeToken<List<WeightLoadedEquipment>>() {}.type
        val accessoryEquipmentsType = object : TypeToken<List<AccessoryEquipment>>() {}.type
        val exerciseMovementsType = object : TypeToken<List<ExerciseMovementBackup>>() {}.type

        val name = jsonObject.get("name")?.takeUnless { it.isJsonNull }?.asString ?: ""
        val workouts = jsonObject.get("workouts")?.let {
            if (it.isJsonNull) emptyList<Workout>() else context.deserialize(it, workoutsType)
        } ?: emptyList()
        val equipments = jsonObject.get("equipments")?.let {
            if (it.isJsonNull) emptyList<WeightLoadedEquipment>() else context.deserialize(it, equipmentsType)
        } ?: emptyList()
        val accessoryEquipments = jsonObject.get("accessoryEquipments")?.let {
            if (it.isJsonNull) emptyList<AccessoryEquipment>() else context.deserialize(it, accessoryEquipmentsType)
        } ?: emptyList()
        val exerciseMovementsElement = when {
            jsonObject.has("exerciseMovements") -> jsonObject.get("exerciseMovements")
            jsonObject.has("ExerciseMovements") -> jsonObject.get("ExerciseMovements")
            else -> null
        }
        val exerciseMovements = exerciseMovementsElement?.let {
            if (it.isJsonNull) emptyList<ExerciseMovementBackup>() else context.deserialize(it, exerciseMovementsType)
        } ?: emptyList()

        return WorkoutPlanPackage(
            name = name,
            workouts = workouts,
            equipments = equipments,
            accessoryEquipments = accessoryEquipments,
            exerciseMovements = exerciseMovements,
        )
    }
}
