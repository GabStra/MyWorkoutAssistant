package com.gabstra.myworkoutassistant.shared.adapters

import com.gabstra.myworkoutassistant.shared.EXERCISE_LIBRARY_PACKAGE_FORMAT
import com.gabstra.myworkoutassistant.shared.ExerciseDefinition
import com.gabstra.myworkoutassistant.shared.ExerciseLibraryPackage
import com.gabstra.myworkoutassistant.shared.ExerciseMovementBackup
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.equipments.AccessoryEquipment
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.google.gson.JsonDeserializationContext
import com.google.gson.JsonDeserializer
import com.google.gson.JsonElement
import com.google.gson.JsonParseException
import com.google.gson.reflect.TypeToken
import java.lang.reflect.Type

class ExerciseLibraryPackageAdapter : JsonDeserializer<ExerciseLibraryPackage> {
    override fun deserialize(
        json: JsonElement,
        typeOfT: Type,
        context: JsonDeserializationContext,
    ): ExerciseLibraryPackage {
        val jsonObject = json.asJsonObject
        val format = jsonObject.get("format")?.takeUnless { it.isJsonNull }?.asString
        if (format != EXERCISE_LIBRARY_PACKAGE_FORMAT) {
            throw JsonParseException("Not a MyWorkoutAssistant exercise library package")
        }

        val definitionsType = object : TypeToken<List<ExerciseDefinition>>() {}.type
        val equipmentsType = object : TypeToken<List<WeightLoadedEquipment>>() {}.type
        val accessoriesType = object : TypeToken<List<AccessoryEquipment>>() {}.type
        val movementsType = object : TypeToken<List<ExerciseMovementBackup>>() {}.type

        return ExerciseLibraryPackage(
            format = format,
            schemaVersion = jsonObject.get("schemaVersion")?.takeUnless { it.isJsonNull }?.asInt
                ?: WorkoutStore.CURRENT_SCHEMA_VERSION,
            exerciseDefinitions = jsonObject.get("exerciseDefinitions")?.let {
                if (it.isJsonNull) emptyList() else context.deserialize(it, definitionsType)
            } ?: emptyList(),
            equipments = jsonObject.get("equipments")?.let {
                if (it.isJsonNull) emptyList() else context.deserialize(it, equipmentsType)
            } ?: emptyList(),
            accessoryEquipments = jsonObject.get("accessoryEquipments")?.let {
                if (it.isJsonNull) emptyList() else context.deserialize(it, accessoriesType)
            } ?: emptyList(),
            exerciseMovements = jsonObject.get("exerciseMovements")?.let {
                if (it.isJsonNull) emptyList() else context.deserialize(it, movementsType)
            } ?: emptyList(),
        )
    }
}
