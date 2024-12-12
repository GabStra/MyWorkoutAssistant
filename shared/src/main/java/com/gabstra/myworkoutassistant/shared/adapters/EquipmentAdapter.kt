package com.gabstra.myworkoutassistant.shared.adapters

import com.gabstra.myworkoutassistant.shared.equipments.*
import com.google.gson.*
import com.google.gson.reflect.TypeToken
import java.lang.reflect.Type
import java.util.UUID

class EquipmentAdapter : JsonSerializer<Equipment>, JsonDeserializer<Equipment> {
    override fun serialize(src: Equipment, typeOfSrc: Type, context: JsonSerializationContext): JsonElement {
        return JsonObject().apply {
            addProperty("id", src.id.toString())
            addProperty("type", src.type.name)
            addProperty("name", src.name)
            addProperty("maxAdditionalItems", src.maxAdditionalItems)
            add("additionalPlates", context.serialize(src.additionalPlates))
            addProperty("volumeMultiplier", src.volumeMultiplier)
            when (src) {
                is Dumbbells -> {
                    add("dumbbells", context.serialize(src.availableDumbbells))
                }
                is Barbell -> {
                    add("plates", context.serialize(src.availablePlates))
                    addProperty("barWeight",src.barWeight)
                    addProperty("barLength", src.barLength)
                }
            }
        }
    }

    override fun deserialize(json: JsonElement, typeOfT: Type, context: JsonDeserializationContext): Equipment {
        val obj = json.asJsonObject
        val id = UUID.fromString(obj.get("id").asString)
        val name = obj.get("name").asString
        val maxAdditionalItems = obj.get("maxAdditionalItems").asInt
        val plateListType = object : TypeToken<List<Plate>>() {}.type
        val dumbbellListType = object : TypeToken<List<DumbbellUnit>>() {}.type

        val additionalPlates = if (obj.has("additionalPlates")) {
            context.deserialize<List<Plate>>(obj.get("additionalPlates"), plateListType)
        } else {
            emptyList()
        }

        val volumeMultiplier = if(obj.has("volumeMultiplier")){  obj.get("volumeMultiplier").asDouble } else{ 1.0 }

        return when (EquipmentType.valueOf(obj.get("type").asString)) {
            EquipmentType.DUMBBELLS -> Dumbbells(
                id = id,
                name = name,
                availableDumbbells = context.deserialize(obj.get("dumbbells"), dumbbellListType),
                additionalPlates = additionalPlates,
                maxAdditionalItems = maxAdditionalItems,
                volumeMultiplier = volumeMultiplier
            )

            EquipmentType.BARBELL -> Barbell(
                id = id,
                name = name,
                availablePlates = context.deserialize(obj.get("plates"), plateListType),
                barLength = obj.get("barLength").asInt,
                additionalPlates = additionalPlates,
                maxAdditionalItems = maxAdditionalItems,
                barWeight = if(obj.has("barWeight")){  obj.get("barWeight").asDouble } else{ 0.0 },
                volumeMultiplier = volumeMultiplier
            )
        }
    }
}